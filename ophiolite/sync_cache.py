"""E28: a local cache of project state kept current from the project's event log.

An event never carries state: it names a subject, and the client re-reads it. What makes the cache
correct is how those re-reads land (the fencing protocol, docs "Keeping a local copy"):

- The fence of a cached subject is the cursor of the event that triggered its read (monotonic within
  one epoch). A write fenced below the subject's current fence is discarded.
- Refreshes of one subject are serialised, and an invalidation that arrives while a read is in flight
  makes that read's answer stale: it is discarded and the subject is read again (R7-4). Two reads
  triggered by the same event therefore never overwrite each other out of order.
- A resynchronisation builds a complete staged snapshot and swaps it in at once, stamped with the head
  cursor captured before enumeration; every read begun before the swap is discarded (the snapshot
  generation fences it), including one that overlaps the resync at exactly the head cursor.
- The cache belongs to one (project, principal, capability digest, epoch). Any change to that scope
  drops everything and requires a resync.
- A stale "access lost" never deletes directly: the subject is re-read; a successful read refreshes it,
  a refused one evicts it.
"""
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Ticket:
    """What a read captured when it began: its subject, the subject's invalidation count and the snapshot."""
    key: tuple
    sequence: int
    generation: int


class Cache:
    def __init__(self, scope):
        self.scope = tuple(scope)
        self._lock = threading.RLock()
        self._subjects = {}  # key -> per-subject refresh lock
        self._entries, self._fences, self._sequence = {}, {}, {}
        self.generation = 0
        self.complete = False  # True once a resync has built a full snapshot

    # -- scope ------------------------------------------------------------------------------------

    def rescope(self, scope):
        """Adopt a new (project, principal, capability digest, epoch). Returns True when it changed; everything
        is dropped and the cache needs a resync."""
        scope = tuple(scope)
        with self._lock:
            if scope == self.scope: return False
            self.scope = scope
            self._entries, self._fences, self._sequence = {}, {}, {}
            self.generation += 1; self.complete = False
            return True

    # -- reading ----------------------------------------------------------------------------------

    def get(self, kind, subject_id):
        with self._lock: return self._entries.get((kind, subject_id))

    def fence(self, kind, subject_id):
        with self._lock: return self._fences.get((kind, subject_id))

    def enumerate(self, kind):
        with self._lock: return {sid: state for (k, sid), state in self._entries.items() if k == kind}

    # -- the protocol -----------------------------------------------------------------------------

    def begin(self, kind, subject_id):
        key = (kind, subject_id)
        with self._lock: return Ticket(key, self._sequence.get(key, 0), self.generation)

    def invalidate(self, kind, subject_id):
        """An event names this subject: any read in flight for it is now stale."""
        key = (kind, subject_id)
        with self._lock: self._sequence[key] = self._sequence.get(key, 0) + 1

    def _admissible(self, ticket, fence):
        if ticket.generation != self.generation: return 'superseded'  # a snapshot swap (or a rescope) happened since it began
        if self._sequence.get(ticket.key, 0) != ticket.sequence: return 'stale'  # invalidated while in flight: read again
        current = self._fences.get(ticket.key)
        if current is not None and fence < current: return 'older'
        return None

    def put(self, ticket, state, fence):
        """Land a read. Returns None when it landed, else why it was discarded ('superseded', 'stale', 'older')."""
        with self._lock:
            refused = self._admissible(ticket, fence)
            if refused: return refused
            self._entries[ticket.key] = state; self._fences[ticket.key] = fence
            return None

    def evict(self, ticket, fence):
        """A refused re-read (access lost, subject gone): drop the entry under the same rules as put."""
        with self._lock:
            refused = self._admissible(ticket, fence)
            if refused: return refused
            self._entries.pop(ticket.key, None); self._fences[ticket.key] = fence
            return None

    def refresh(self, kind, subject_id, fence, read, attempts=5):
        """Re-read one subject for the event at `fence`, serialised per subject; re-read while an invalidation
        lands during the read. `read()` returns the state, or raises LookupError when the subject is no longer
        readable (evicted). Returns the outcome of the last attempt."""
        key = (kind, subject_id)
        with self._lock: gate = self._subjects.setdefault(key, threading.Lock())
        with gate:
            for _ in range(attempts):
                ticket = self.begin(kind, subject_id)
                try: state = read()
                except LookupError: outcome = self.evict(ticket, fence)
                else: outcome = self.put(ticket, state, fence)
                if outcome != 'stale': return outcome
            return 'stale'

    def replace_all(self, staged, head_fence):
        """Swap in a complete snapshot {(kind, subject_id): state} built by a resync, stamped with the head cursor
        captured before its enumeration began. Readers never see a partial snapshot; reads begun before the swap
        are discarded."""
        staged = dict(staged)
        with self._lock:
            self._entries = staged
            self._fences = {key: head_fence for key in staged}
            self._sequence = {}
            self.generation += 1; self.complete = True
