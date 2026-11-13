---
name: exchange-with-a-notebook
description: As an assistant, read a log into a lasio or pandas notebook, run the person's trusted procedure over it, and send the result as one run the person approves.
---
<!-- sdk-contract: {"routes":["/api/v1/projects/{project}/procedure-runs/report"],"symbols":["ophiolite.agents.AgentClient.exchange","ophiolite.client.Client.read","ophiolite.client.Client.download_original","ophiolite.agent_exchange.AgentExchange.send_run","ophiolite.lasio.to_lasio","ophiolite.procedures.run","ophiolite.procedures.ProjectInput"],"errors":["integrity-conflict"]} -->

Use only the tool's own interface and Ophiolite's SDK; never open or decode the tool's project files. Here the tool is a
lasio or pandas notebook: read and compute with lasio and pandas, never by opening the notebook file itself.

What stays the person's: signing in, giving an application consent, installing anything, and registering, trusting and
verifying the procedure you run. You may check, get, run that procedure on this computer, and ask to send its output.
Nothing is published until the person approves.

Given `agent` (your `AgentClient`), `work` (your exchange folder), `log_id` (the log the person named),
`procedure_folder` (the person's procedure on this computer) and `verified` (the digest the person verified):

```python
from ophiolite import procedures
from ophiolite.lasio import to_lasio
from ophiolite.procedures import ProjectInput

ex = agent.exchange(work)
ex.check()                                             # what is new since this folder last looked
ex.get(log_id, curves=["GR"])                          # this folder now holds the log at one exact version
held = ex.held()[log_id]["revision"]
las = to_lasio(agent.reads.read(log_id, held, ["GR"]))
frame = las.df()                                       # show the person the curve you will use
original = work / "log.las"
agent.reads.download_original(log_id, held, original)  # the file the procedure reads, at the held version
procedures.run(procedure_folder, work / "ran",
               inputs={"log": [ProjectInput(str(original), "las2/1", {}, log_id, held)]},
               expected_digest=verified)               # the copy that runs is the version the person verified
asked = ex.send_run(work / "ran", name="Shale volume", wait=False)
```

`asked` says the send waits for approval. Tell the person; do not run the procedure again. After they approve, send the
same run again from the same folder (in this session or a later one), which publishes it:

```python
sent = agent.exchange(work).send_run(work / "ran", name="Shale volume", wait=False)
```

The run reads the version this folder holds, not the latest: if the log changed after your get, the result is still
made from the version you showed the person. A plain `send` is refused (no tool ran it), and so is an output that is a
file to upload rather than a result. A newer version added before approval ends the send with nothing published.

Evidence: the example is tested against the conformance target with lasio and pandas as installed; the notebook file
sits in the same folder and the test fails if the example opens it. That is harness evidence; a claim that it works in
a particular notebook host needs that host's evidence (ADR 0015).
