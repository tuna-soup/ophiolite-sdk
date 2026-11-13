---
name: exchange-with-opendtect
description: As an assistant, check what is new for an OpendTect survey and get a project horizon into it through the ophiolite-opendtect connector and odbind; sending stays the person's.
---
<!-- sdk-contract: {"routes":[],"symbols":["ophiolite.agents.AgentClient.exchange","ophiolite.agent_exchange.AgentExchange.check"],"errors":[]} -->

This skill needs the ophiolite-opendtect connector (and OpendTect's odbind) installed on this computer by the person;
without it, stop and say so. Installing it is the person's step, not yours.

Use only the tool's own interface and Ophiolite's SDK; never open or decode the tool's project files. Here the tool is
OpendTect: the connector reads and writes the survey through odbind, and you never open a file in the survey folder.

What stays the person's: signing in, giving an application consent, installing anything, and sending from the survey.
You may check what is new and get a horizon into the survey; the survey's record folder is your exchange folder.

Given `agent` (your `AgentClient`), `survey_root` and `survey_name` (the survey the person named) and `item` (the
horizon the person asked for):

```python
from pathlib import Path
from ophiolite_opendtect import exchange
from ophiolite_opendtect.survey import Survey

survey = Survey(Path(survey_root), survey_name)
ex = agent.exchange(survey.record)                    # the survey's own record folder holds what it has
news = exchange.check(ex)                             # what is newer in the project than what the survey holds
got = exchange.get("horizon", ex, agent.reads, survey, item)  # a new horizon beside the person's, never over it
```

Tell the person the horizon's name in the survey (`got.facts["object"]`) and what OpendTect stored differently, if
anything (`got.facts["moves"]`).

Sending a horizon back is the person's connector command (`send horizon NAME` with their own key file), not yours: the
connector refuses an assistant's send before it reads the survey, and nothing is published. Do not use the
connector's own sign-in or its key file; your access is the `agent` you were given.

Evidence: the example is tested against the conformance target with a stand-in for odbind holding a synthetic survey;
the test fails if the example opens a file in the survey folder itself. That is harness evidence; a claim that it works
with a particular OpendTect installation needs that installation's evidence (ADR 0015).
