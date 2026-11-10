"""E142 s1 C3b: `ophiolite data survey ID --json` prints the gathered survey (`--latest` reads the live view; words name
each relation by its members' labels); `data surveys` lists them. The fake gateway is test_surveys_client's."""
import json

from ophiolite import cli
from test_surveys_client import Gateway, RELATIONS, SID, client


def test_the_command_line_prints_the_gathered_survey(capsys):
    c = client(Gateway())
    shown = cli._surveys(cli.parser().parse_args(['survey', SID, '--json']), c)
    assert json.loads(capsys.readouterr().out) == shown and [m['label'] for m in shown['members']] == ['syn-%d' % i for i in range(7)]
    assert shown['relations'] == RELATIONS and shown['view'] == 'revision'
    g = Gateway()
    cli._surveys(cli.parser().parse_args(['survey', SID, '--latest']), client(g))
    assert g.bodies[0][1]['view'] == 'latest' and 'syn-1 horizon-of syn-0' in capsys.readouterr().out
    listed = cli._surveys(cli.parser().parse_args(['surveys']), c)
    assert [s['survey_id'] for s in listed['surveys']] == [SID, 'other']


def test_both_verbs_are_in_the_data_group():
    assert cli.parser().parse_args(['data', 'survey', SID, '--revision', '2']).revision == 2
    assert cli.parser().parse_args(['data', 'surveys']).command == 'surveys'
