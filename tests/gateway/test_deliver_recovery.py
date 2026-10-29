"""E109 S2.2, gateway lane (C3 tests 3, 12 and 12a, M1, with C5 tops): what the next `ophiolite deliver` says after the
computer stopped mid-delivery, against the real catalogue, record and Activity routes and a throwaway PostgreSQL cluster
(tests/fixtures/e109/pg.py; it fails, never skips, without initdb, 6-18).

The tops-to-team-db example writes the delivery id first in its transaction and declares `reconcile`, which commits a
`withdrawn` tombstone for the id and says not sent only when that commits (4-1). Here: a parent stopped after the
destination's commit is reconciled to confirmed with the tops written once (M1, test 3); a writer stopped before its id
insert is recorded unknown, then not sent through the tombstone, and a late writer with the same id fails on the key
(12a); a writer whose transaction escaped the killed process group keeps the outcome unknown until it commits, then
confirmed (12). The tombstone rule at the function level (an unfenced database, the late writer) is in
test_deliver_tops.py."""
import json
import os
import signal
import time
from pathlib import Path

import pytest
try:
    from project_gateway.tests.real_credentials import project as world  # noqa: F401 (fixture)
    from project_gateway.tests.test_access_foundations import access  # noqa: F401 (fixture)
    from project_gateway.tests.test_organizations import service  # noqa: F401 (fixture)
except ImportError:
    if os.environ.get('OPHIOLITE_REQUIRE_GATEWAY') == '1': raise
    pytest.skip('Platform test runtime is needed for the gateway lane', allow_module_level=True)
from test_deliver_journey import DESTINATION, deliver, deliveries, journey, story_deliveries  # noqa: F401 (fixture)
from test_deliver_tops import THREE, pg, writer
from ophiolite import procedures

UNKNOWN = 'Outcome unknown for %s by Tops to team DB on this computer.' % DESTINATION


class Stopped(BaseException):
    """The parent CLI stopping (its computer died) at the point a test chooses; BaseException, as a kill is not an error."""


def held(j, statement):
    """An owner's open transaction on the team database holding `statement`'s lock until closed."""
    import psycopg
    db = psycopg.connect(j['db'].cluster.dsn(dbname='team_tops'))
    db.execute(statement)
    return db


def until(condition, what):
    """Wait for a database state the test itself set up (no wall-clock budget is asserted; the bound only ends a hang)."""
    for _ in range(600):
        if condition(): return
        time.sleep(0.05)
    raise AssertionError('never happened: ' + what)


def writer_waits_on_a_lock(j):
    return bool(j['db'].rows("SELECT count(*) FROM pg_stat_activity WHERE usename = %s AND wait_event_type = 'Lock'", pg.WRITER)[0][0])


def writer_gone(j):
    return not j['db'].rows('SELECT count(*) FROM pg_stat_activity WHERE usename = %s', pg.WRITER)[0][0]


def stopped_before_the_insert(j, monkeypatch):
    """The writer is held before its id insert by an owner's table lock, then its process group is killed: nothing of
    this delivery ever commits. Returns the folder of the attempt."""
    lock = held(j, 'LOCK TABLE team.deliveries IN SHARE ROW EXCLUSIVE MODE')
    folders = []
    def kill(process, folder):
        until(lambda: writer_waits_on_a_lock(j), "the writer's id insert waits")
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        lock.close()  # the killed writer's session ends with nothing committed
        until(lambda: writer_gone(j), "the killed writer's session ends")
        folders.append(folder)
    monkeypatch.setattr(procedures, '_launched', kill)
    answer = deliver(j)
    monkeypatch.undo()
    assert folders == [Path(answer['folder'])]
    return answer


def test_a_parent_stopped_after_the_commit_is_confirmed_by_reconcile_with_the_tops_written_once(journey, monkeypatch):
    j = journey
    def stop(process, folder):  # M1: the writer commits and answers; the parent dies before it saves the answer
        process.wait()
        raise Stopped()
    monkeypatch.setattr(procedures, '_launched', stop)
    with pytest.raises(Stopped): deliver(j)
    monkeypatch.undo()
    assert deliveries(j['alice']) == []  # nothing reported before the parent stopped
    [folder] = [p for p in (j['work'] / 'deliveries').iterdir()]
    again = deliver(j)  # the next run finds the waiting attempt, never sends again, and asks the destination
    assert again['delivery_id'] == folder.name
    assert again['sentence'] == 'Sent to %s by Tops to team DB on this computer: 3 items. Recorded in the project.' % DESTINATION
    assert (again['state'], again['items'], again['reported']) == ('confirmed', 3, True)
    assert j['db'].rows('SELECT well, surface, md FROM team.tops ORDER BY md') == THREE  # written once
    assert j['db'].rows('SELECT delivery_id, state, items FROM team.deliveries') == [(folder.name, 'delivered', 3)]
    [row] = deliveries(j['alice'])
    assert (row['delivery_id'], row['state'], row['items']) == (folder.name, 'confirmed', 3)


def test_a_writer_stopped_before_its_insert_is_unknown_then_not_sent_through_the_tombstone(journey, monkeypatch):
    j = journey
    first = stopped_before_the_insert(j, monkeypatch)
    assert first['sentence'].startswith(UNKNOWN) and first['sentence'].endswith('Recorded in the project.')
    assert (first['state'], first['reported']) == ('unknown', True)
    [row] = deliveries(j['alice'])  # Activity reads "Outcome unknown for ..." (the Workspace's words, S2.3)
    assert (row['delivery_id'], row['state']) == (first['delivery_id'], 'unknown')
    [entry] = story_deliveries(j['alice'], j['asset'], j['v1'])
    assert entry['state'] == 'unknown'
    assert j['db'].rows('SELECT count(*) FROM team.deliveries') == [(0,)]  # absent: not yet a reason to say not sent
    again = deliver(j)
    assert again['delivery_id'] == first['delivery_id']
    assert again['sentence'] == 'Not sent to %s by Tops to team DB on this computer. Recorded in the project.' % DESTINATION
    assert (again['state'], again['reported']) == ('not-sent', True)
    assert j['db'].rows('SELECT delivery_id, state FROM team.deliveries') == [(first['delivery_id'], 'withdrawn')]
    [row] = deliveries(j['alice'])
    assert (row['delivery_id'], row['state']) == (first['delivery_id'], 'not-sent')
    import psycopg
    with pytest.raises(psycopg.errors.UniqueViolation):  # a late writer with the same id cannot pass the tombstone
        writer.write(j['db'].config, [(w, s, md) for w, s, md in THREE], first['delivery_id'])
    assert j['db'].rows('SELECT count(*) FROM team.tops') == [(0,)]


def test_an_escaped_writer_keeps_the_outcome_unknown_until_it_commits_then_confirmed(journey, monkeypatch):
    j = journey
    first = stopped_before_the_insert(j, monkeypatch)
    import psycopg
    escaped = psycopg.connect(**{k: j['db'].config[k] for k in ('host', 'port')}, dbname='team_tops', user=pg.WRITER)
    escaped.execute('INSERT INTO team.deliveries (delivery_id, state, items) VALUES (%s, %s, %s)', (first['delivery_id'], 'delivered', 3))
    with escaped.cursor() as cursor:  # outside the killed group: its id insert is in, its commit not yet (2-1, 4-14)
        cursor.executemany('INSERT INTO team.tops (well, surface, md) VALUES (%s, %s, %s)', THREE)
    again = deliver(j)  # the tombstone waits on the open row, gives up, and says unknown: never not sent
    assert again['sentence'] == '%s It was not sent again. Recorded in the project.' % UNKNOWN
    assert again['state'] == 'unknown'
    escaped.commit()
    escaped.close()
    last = deliver(j)
    assert last['sentence'] == 'Sent to %s by Tops to team DB on this computer: 3 items. Recorded in the project.' % DESTINATION
    assert j['db'].rows('SELECT well, surface, md FROM team.tops ORDER BY md') == THREE
    assert j['db'].rows('SELECT delivery_id, state, items FROM team.deliveries') == [(first['delivery_id'], 'delivered', 3)]
    [row] = deliveries(j['alice'])
    assert (row['delivery_id'], row['state'], row['items']) == (first['delivery_id'], 'confirmed', 3)
