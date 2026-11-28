"""E217 s0 (D6): result reads answer their validated models. Never executed."""
from typing_extensions import assert_type

from ophiolite import Client
from ophiolite.client import Provenance
from ophiolite.models.api import Grants, History, HistoryEntry, ResultDiff, ResultGroup, ResultSummary, RestrictedResultSummary
from ophiolite.models.generated import SearchAnswer, SearchAnswerByMeaning


def results(client: Client) -> None:
    result: dict[str, str] = {'asset_id': 'a', 'revision': 'r', 'authority': 'ophiolite:derived'}
    history = client.history(result)
    assert_type(history, History)
    assert_type(history.revisions[0], HistoryEntry)
    assert_type(client.result_groups(), list[ResultGroup])
    assert_type(client.diff(('a', 'r1'), ('a', 'r2')), ResultDiff)
    assert_type(client.results(), list[ResultSummary | RestrictedResultSummary])
    assert_type(client.grants(result), Grants)
    assert_type(client.provenance('asset', 'revision'), Provenance)
    assert_type(client.find('organization', 'gamma ray'), SearchAnswer | SearchAnswerByMeaning)
