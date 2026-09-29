"""E28 C6: the cache fencing protocol (ophiolite.sync_cache)."""
import threading
from ophiolite.sync_cache import Cache

SCOPE = ('p', 'alice', 'caps-1', 'epoch-1')


def test_fences_are_event_cursors_not_the_enclosing_entity_generation():
    """An association change and a member's head change never advance the well's own generation; the event cursor
    still orders the reads."""
    cache = Cache(SCOPE)
    well = lambda parts: {'id': 'well-1', 'generation': 1, 'parts': parts}  # the same generation in every state
    assert cache.put(cache.begin('entity', 'well-1'), well(['b1']), 5) is None
    assert cache.put(cache.begin('entity', 'well-1'), well(['b1', 'b2']), 7) is None
    late = cache.begin('entity', 'well-1')
    assert cache.put(late, well(['b1']), 6) == 'older' and cache.get('entity', 'well-1')['parts'] == ['b1', 'b2']


def test_a_slow_read_overtaken_by_a_newer_event_never_lands():
    cache = Cache(SCOPE)
    slow = cache.begin('uploaded', 'a1')  # a read for the event at cursor 3 is in flight
    cache.invalidate('uploaded', 'a1')  # the event at cursor 4 arrives
    assert cache.put(cache.begin('uploaded', 'a1'), {'revision': 'r2'}, 4) is None
    assert cache.put(slow, {'revision': 'r1'}, 3) == 'stale' and cache.get('uploaded', 'a1') == {'revision': 'r2'}


def test_two_reads_for_the_same_event_are_serialised_and_an_invalidation_forces_a_reread():
    """R7-4: equal fences no longer race. The first read is slow and sees the old state; an invalidation for the
    same subject arrives during it; refresh reads again and lands the current state."""
    cache = Cache(SCOPE)
    states = iter([{'head': 'old'}, {'head': 'new'}, {'head': 'new'}])
    entered, release = threading.Event(), threading.Event()
    def slow_read():
        state = next(states)
        if state['head'] == 'old': entered.set(); release.wait(5)
        return state
    outcomes = []
    t = threading.Thread(target=lambda: outcomes.append(cache.refresh('result-group', 'g1', 9, slow_read)))
    t.start(); entered.wait(5)
    cache.invalidate('result-group', 'g1')  # a second event for the group while the first read is in flight
    second = threading.Thread(target=lambda: outcomes.append(cache.refresh('result-group', 'g1', 9, lambda: next(states))))
    second.start()
    release.set(); t.join(5); second.join(5)
    assert outcomes == [None, None] and cache.get('result-group', 'g1') == {'head': 'new'}


def test_a_refused_reread_evicts_and_a_restored_one_refreshes():
    cache = Cache(SCOPE)
    cache.put(cache.begin('uploaded', 'a1'), {'name': 'Log'}, 2)
    def gone(): raise LookupError('Asset unavailable')
    assert cache.refresh('uploaded', 'a1', 3, gone) is None and cache.get('uploaded', 'a1') is None
    # a stale access-lost replayed after access came back: the re-read succeeds and the entry returns
    assert cache.refresh('uploaded', 'a1', 4, lambda: {'name': 'Log'}) is None and cache.get('uploaded', 'a1') == {'name': 'Log'}


def test_a_staged_swap_is_never_partial_and_reads_begun_before_it_are_discarded():
    cache = Cache(SCOPE)
    cache.put(cache.begin('entity', 'e1'), {'v': 1}, 1)
    before = cache.begin('entity', 'e2')  # a read overlapping the resync, at exactly the head cursor
    seen, stop = [], threading.Event()
    def watch():
        while not stop.is_set():
            snapshot = cache.enumerate('entity')
            seen.append(tuple(sorted(snapshot)))
    t = threading.Thread(target=watch); t.start()
    cache.replace_all({('entity', 'e1'): {'v': 2}, ('entity', 'e2'): {'v': 2}, ('entity', 'e3'): {'v': 2}}, 10)
    stop.set(); t.join(5)
    assert set(seen) <= {('e1',), ('e1', 'e2', 'e3')}  # the old snapshot or the new one, never a mixture
    assert cache.put(before, {'v': 'overlap'}, 10) == 'superseded' and cache.get('entity', 'e2') == {'v': 2}
    after = cache.begin('entity', 'e2')
    assert cache.put(after, {'v': 3}, 11) is None and cache.complete


def test_a_scope_change_drops_everything_and_requires_a_resync():
    cache = Cache(SCOPE)
    cache.replace_all({('entity', 'e1'): {'v': 1}}, 5)
    inflight = cache.begin('entity', 'e1')
    assert not cache.rescope(SCOPE)
    assert cache.rescope(('p', 'alice', 'caps-2', 'epoch-1'))  # the capability set changed
    assert cache.get('entity', 'e1') is None and not cache.complete and cache.put(inflight, {'v': 9}, 6) == 'superseded'
