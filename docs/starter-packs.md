# Starter packs

A starter pack is a small, ready-to-open set of files made from one Open Subsurface Data catalogue record: the
record's held inputs, the decisions a reader needs to interpret them, and target files made from them (for a well
pack, a Python import script, the well heads in WGS84 and an attribution file; for a survey archive, an OpendTect
import script and an attribution file). Its document is `osd.starter/1`;
`ophiolite starter` builds it against an Ophiolite project and fills in its custody keys. The command reference is
[the CLI page](cli.md#starter).

Install the starter extra first; it brings the LAS and coordinate readers:

```sh
pip install 'ophiolite[starter]'
```

## The definition

You write one JSON file, `ophiolite.starter-definition/1`, beside the input files. It names:

- `id` (`<record id>/<pack>`), `record_id`, `title`, `summary`, and `built_at`, the only time the pack carries (a
  rebuild of the same definition gives the same bytes);
- `recipe`: `id`, `repository` (https) and `commit` (40 hex) of what built it;
- `targets`: `["python"]`;
- `inputs`: each `name`, `file` (a path inside the definition's folder), `sha256`, `bytes`, `well`, `held` (either
  `{"as": "verified", "verifier_run": {checked_at, tool_version}, "path"}` for a file of the record's latest
  verification, or `{"as": "deposited", "key"}` for a maintainer's deposit), and for a tops or deviation CSV its own
  `declare` values (`depth_basis`, `azimuth_reference`);
- `contents`: `[{kind, ids}]`, kinds `wellbore-logs`, `tops` and `wellbore-paths`;
- `decisions`: for every well, once each: `crs`, `vertical-datum`, `depth-reference`, `depth-kind`, `units`, `nulls`,
  `names`, each with its `value` and `source` (`publisher`, `data` or `chosen`; a chosen value needs a `note`).

A worked, synthetic example is in the Integration repository at `conformance/fixtures/starter/`.

What the decisions do:

| Decision | Used for |
|---|---|
| `crs` | placing each LAS well head (`XCOORD`, `YCOORD`) in WGS84 |
| `units`, `nulls`, `names` | checked against each LAS head: depth unit, `NULL` and `WELL` must agree |
| `units`, `depth-reference` | the `depth_unit` and `depth_datum` declarations of the well's tops and deviation files |
| the others | written into the pack for its readers |

`names` supports exactly the well's own name in this version.

## Build

```sh
ophiolite starter build definition.json --out pack --catalogue records.json --verification verification --custody custody
```

`records.json` is the built catalogue, `verification` the folder of latest verification results, and `custody` the
folder of custody documents. Before anything is sent, `build` checks the definition, each local file against its
SHA-256 and size, every decision, the LAS heads, each input's evidence and the pack licence those give (an input
whose licence does not allow redistribution, or a combination of licences that differ, is refused). Then it adds each
input to the project, at an exact version, and writes into `pack/`:

- `starter.json`, with `unpublished: true` and no artefact keys yet;
- `fidelity/<pack>.json`, what each input became in the project;
- `files/`, the artefacts: `targets/python/open_pack.py`, `targets/python/heads/<well>.geojson` and `ATTRIBUTION.md`;
- `evidence.json`, the evidence it judged, and `landing.json`, its journal.

A survey archive is built from its export (below) instead:

```sh
ophiolite starter build export.json --export export --out pack --catalogue records.json --verification verification --custody custody
```

`--export` names the folder `ophiolite starter export` wrote. The build checks the export against the definition and
its own report, then adds each derived file (cubes, horizons, well tracks, logs) to the project, at an exact version,
with the declarations the survey gives. A horizon with more nodes than the deployment takes (its `horizon_nodes`,
1,000,000 unless set otherwise) is not added: its fidelity row is `failed` with "This horizon has more nodes than
Ophiolite takes (1,000,000).", naming that number, and the OpendTect import still places it. A horizon that is added
is read back and compared with its file in node order (the first, the last and a window from the middle).
`files/` holds `targets/opendtect/import.py`, `ATTRIBUTION.md` and every derived file at the one path the export gave
it (`files/seismic/<cube>.sgy`, `files/horizons/<horizon>.csv`, …): the same path in `derived` and among the
target's artefacts, so it is published with the pack and the import reads it there. The mirror keeps one copy per
SHA-256, so the same bytes never sit at two paths of a pack: a derived file with the bytes of another, or an artefact
with the bytes of a derived file at another path, is refused. The export is bound by its content, so a rerun with
another export is refused.

## Resuming

`landing.json` records each input before any of its content is sent. If a build stops, run the same command with
the same `--out`: an input already added is checked to still be the project's current version and is not sent
again; an upload that had started is read back from its own run, never sent a second time. A rerun with another
server, project, definition or evidence file is refused; build in a new folder.

If an input has a newer version in the project than the one the pack was built from, the build stops with exit 4:
build again in a new folder.

## Finalise

After the artefacts in `files/` are uploaded to the catalogue's mirror (which writes a `derived` custody document
for each), run:

```sh
ophiolite starter finalise pack --custody custody
```

It works on this computer only. It checks the pack again (the evidence it was built from, the licence, the decisions,
the local artefact bytes, the fidelity document, and each deposit against its custody document now: a removal wins)
and then writes every artefact's `key`, read from its held `derived` custody document, all at once. Any refusal leaves
`starter.json` byte-identical. The pack stays unpublished. A survey archive pack is refused until its OpendTect
target has been compared, and its Python target (if any) run (their oracles no longer say "nothing yet"; see below).

## Export a survey archive

A record whose data is an OpendTect survey held as one zip is exported first; `build` refuses a definition with an
archive input. The export definition has the same form with exactly one input, the archive, which adds
`"archive": {"survey": FOLDER, "log_step": METRES, "outline_input": {"name", "url", "sha256"}}`; its contents name
cubes (`seismic-3d`), `horizons`, `wellbore-paths` and `wellbore-logs`, and its decisions give each cube and horizon
its `crs`, `domain`, `units` and `nulls` (and `velocity` in a depth survey), each well its well topics, and the
archive one `units` decision, the log step, chosen with its note.

```sh
ophiolite starter export export.json --out export --catalogue records.json --verification verification \
  --custody custody --opendtect-python /opt/OpendTect/bin/python
```

Two interpreters take part. This SDK checks the definition and the archive against the catalogue evidence, extracts
the archive (no absolute or parent paths, links, duplicates, more than 200 000 members or 8 GiB), and runs the
OpendTect connector (`ophiolite-opendtect`, GPL, installed in OpendTect's own Python; name it with
`--opendtect-python` or `OPHIOLITE_OPENDTECT_PYTHON`, with `DTECT_APPL` naming the installation, whose data-root
template the extracted survey is opened with) in its own process. The connector reads the survey through
odbind only and writes SEG-Y rev 1 (IEEE) per cube, a points CSV per horizon (`x,y,z,inline,crossline`, one row
per node of the horizon's grid, an empty `z` where it has no value), `md,x,y,tvdss` per well track and LAS 2.0 per
well's logs. The logs are resampled by odbind on the log step by linear interpolation: the LAS is not the survey's own
sampling. The SDK then reads every file again with its own readers (lasio for LAS) and refuses unless each holds what
odbind gave, and unless the decisions agree with the survey. It also writes `outline.geojson` (one polygon per cube
from its corners, one point per well head, WGS84): the record's outline, which the report names on its own; it is not
one of the derived files and is not added to the project.

Each run writes a new `export/exports/<UTC stamp>-<n>/` (`files/` and, last, `derived.json`) and then moves
`export/derived.json`, a pointer `{"export": "exports/<name>"}`, to it. A finished folder is never changed. A run
that stops or is refused leaves the previous pointer and folders as they were; its own unfinished folder is removed by
the first export more than 24 hours later. One export runs at a time per folder (`export/.lock`). `derived.json` is an
intermediate report for the pack build that will read it; its form may change without notice.

### 2D lines

The contents may also name 2D seismic lines, `seismic-2d`, each as `DATASET/LINE` (the OpendTect 2D dataset and the
line in it), with the same four decisions as a cube. The connector writes each line as its own SEG-Y rev 1 (IEEE)
file, `seismic2d/DATASET/LINE.sgy`: one trace per trace of the line in OpendTect's order, the trace number at byte
21 (and 193), the source point at byte 197 with its scalar at 201 (none: both 0), x and y at bytes 181 and 185 in
hundredths with scalar -100, and cards C6-C8 of the textual header naming it (`C 6 OPHIOLITE 2D SEISMIC LINE`,
`C 7 DATASET ...`, `C 8 LINE ...`). Trace numbers, source points (as float32), samples and Z are kept exactly;
x and y are rounded to 0.01 m (half to even), as a cube's are, so a position may move by up to 0.005 m.

The export refuses a line by name, before it writes anything, when: its name is not printable ASCII, has a leading
or trailing space, or is longer than 68 characters; it is not in two-way time in milliseconds; it has more than one
component; it has more than 200,000 traces or 20,000 samples per trace; its samples are not on one sampling; it holds
a trace number twice; a sample is not finite or is OpendTect's undefined value; a source point cannot be written
exactly with up to four decimals; more than 64 of its traces have no source point; or a position does not fit SEG-Y.
A survey in depth is refused for lines ("2D lines are landed in time (ms) only in this version").

The SDK reads every line again with its own parser and refuses unless its cards name it, its traces are the ones
export.json states and its first and last trace, count and Z agree with the export's report. The outline has one
`survey-2d` feature per line through every trace position in file order (a point for a line of one trace). In the
project each line is added as `segy-line/1` with the survey's CRS and Z domain, and its fidelity row ends with
`lines of dataset DATASET in this pack: N of M`, M being how many lines the dataset holds in OpendTect.

### Faults

The contents may also name faults, `faults`, by their OpendTect name: a fault stick set or a 3D fault, with the
decisions `crs`, `domain` (`time`) and `units` (`s`). The connector writes each as OpendTect fault-stick text,
`faults/NAME.dat`: the line `# OpendTect FaultStickSet`, then one line per point, `x y z stick`, sticks numbered from 0
in OpendTect's order and every number exactly as OpendTect holds it. Z is two-way time in seconds, as OpendTect gives a
fault's coordinates, whatever unit the survey shows. A fault's sticks are kept; a 3D fault's surface between them is
not, and a stick set drawn on 2D lines keeps its sticks but not the lines they were drawn on.

The export refuses a fault by name, before it writes anything, when: the survey holds no fault of that name, or both a
stick set and a 3D fault of it; it holds no sticks, or a stick of fewer than two points; a coordinate is not finite or
is OpendTect's undefined value; it is in depth; it has more than 20,000 sticks or 200,000 points; or the survey's
coordinates are not in metres. The SDK reads every fault again and refuses unless it is in the export's own form and
its sticks and points are the ones export.json states. Faults add nothing to the outline, and a pack whose Python
target has neither a cube nor a 2D line is refused. In the project each fault is added as `opendtect-faultsticks/1`,
time in seconds.

OpendTect cannot create a fault from Python, so the OpendTect import tells you, for each fault, the one step: import
its file in OpendTect (Survey > Import > FaultStickSets > ASCII 3D > Single 3D FaultStickSet, header 1 line, stick
index in column 4, time in seconds) under the name it gives. The next run of the import (and of `ophiolite starter opendtect`) reads that stick set back and records it as placed by you
when every point agrees within 0.5 mm in x and y and 0.5 µs in Z. A fault whose coordinate system, xy unit or time
domain is not the survey's is refused before anything is compared, and so is a stick set holding an undefined value. ResInsight does not import fault sticks in this version, and the pack notebook does not read them; each says
so in its oracle.

### Time-depth models

The contents may also name time-depth models, `time-depth`, one per well, from checkshot tables in the archive. Each
well named there must also be under `wellbore-paths`, and the archive says where its table is: the key `time_depth`,
per well `{member, header_line, delimiter, depth, time}`: the archive file, the line of its column names, `tab` or
`comma`, and the names of the depth and time columns. The decisions of each well say what the numbers mean:
`depth-kind` (MD, TVD or TVDSS), `units` (the depth unit), `vertical-datum`, and `domain`, for example
`two-way time in ms` (one-way or two-way; s, ms or us).

The SDK writes each table as `wells/WELL-time-depth.csv`: the header `depth,time`, then the two named columns of each
row, the text unchanged. It refuses the model by name, with nothing written, when: the file is not in the archive or
is a folder; the header line or a column is missing; a cell is not a finite number; depth or time does not increase
strictly from one row to the next (compared as the numbers they are, so `1.00000000000000002` after
`1.00000000000000001` does not increase); there are fewer than 2 or more than 100,000 pairs; or the written file would
be larger than 16 MiB. No repair is applied. Every model is checked before any is written. In the project each model
is added as `time-depth-csv/1` with its own well's declarations.

OpendTect's Python cannot read or write a well's depth/time model, so the OpendTect import never places one and cannot
verify one: for each model it tells you the step (Survey > Manage > Wells, select the well, Edit Depth/Time model,
Import ..., with the depth kind, time kind and units of that model in OpendTect's own labels) and says "Import this model in OpendTect; this starter cannot
verify the imported model." When the survey has no such well yet, it tells you to import the well path first, run
the import again, and then import the model. The pack notebook reads every model and compares every pair with
`expected.json`. ResInsight does not import time-depth models from a starter pack; its oracle says "Time-depth
models: not placed".

## The OpendTect target

A survey archive pack's target is `files/targets/opendtect/import.py`. It places the pack's seismic cubes, horizons,
2D lines and logs in an existing OpendTect survey from the pack's own files; it reads nothing from Ophiolite and sends nothing
to it. Run it with the Python the OpendTect connector is installed in (measured with OpendTect 7.0.10; check your
installation with `python -m ophiolite_opendtect.host DTECT_APPL`):

```sh
python pack/files/targets/opendtect/import.py pack --survey DATAROOT/SURVEY
```

Before writing anything it checks every file of the pack it reads (cubes, horizons, well paths and LAS files) against
`starter.json` (size and SHA-256, a regular file, not a link) and opens the survey. Each cube must lie on the survey's sampling (coordinate system, metres, corner positions, Z domain and unit,
inline, crossline and Z on the survey's lattice); it is written as a new cube, one inline at a time, and read back bit
for bit. Each horizon must be in time (milliseconds, positive down) in the survey's coordinate system with every node
on the survey's grid; it is written as a new horizon. New objects are named `<object> · Ophiolite v1`, beside what
the survey already holds. An object the checks refuse is not placed and the import says why; the others are placed.
What was placed is recorded in the survey's `Ophiolite` folder, so a second run answers `already` and writes nothing.
`--compare` writes nothing: it reads each placed object back and compares it with the pack's file (a cube bit for
bit; a horizon's Z within half of OpendTect's 16-bit storage step for that inline, positions within 1 cm, empty nodes
as sets).

**2D lines.** The lines of each pack dataset are placed together in a new 2D dataset `<dataset> · Ophiolite` (the
next free name), beside the survey's own; nothing is written until every line has been checked. A line is placed only
when the survey and the line are in two-way time in milliseconds, the line is in the survey's coordinate system and
metres, its file is the export's own layout and its textual header names the dataset and line `starter.json` names,
its trace numbers increase (OpendTect keeps a line's traces in that order), every sample is defined, and its dataset and line names are ones OpendTect keeps as
they are. OpendTect keeps one geometry per line name: a line without one gets its own; a geometry of that name with the
same trace numbers in the same order, the same source points and the same positions to the centimetre is reused and
never written; any other geometry refuses that line ("The OpendTect survey already has a geometry for line …") and
stays as it is, while the dataset's other lines are placed. Each line is read back bit for bit and recorded, so a
second run answers `already`. A run that stops while writing leaves a dataset the next run names ("OpendTect stopped
while writing …; delete it in OpendTect if you do not want it.") and never reopens; the next run places the lines
again under the next free name. A placed dataset that you delete, edit or that holds an earlier version of the pack's
lines is said so, and the lines are placed again beside it. `--compare` counts per line the samples, trace numbers,
source points, positions (to the centimetre) and Z that differ.

**Logs.** Each curve of each LAS file is placed or refused on its own, as a new log on the survey's well of the same
name (the pack's well, not its file name, pairs them). OpendTect 7.0.10 cannot create a well from Python, so the well
must already be in the survey: import its well path in OpendTect first (Survey > Import > Wells, from
`files/wells/WELL-positions.csv`); every well path is listed as not placed with that step. A curve is written only when:

- the pack has the well's path, and its head matches the survey's well within 1 cm on each axis, in the survey's
  coordinate system;
- the pack states the depth reference: measured depth in metres below the kelly bushing, as OpendTect keeps it
  (`ophiolite starter build` declares well paths exported from OpendTect so). A pack built before this version says
  the reference is unknown, and its logs are refused with "The pack does not state this well's depth reference."
  until it is built again;
- the LAS depths are in metres and the survey neither stores nor shows depths in feet;
- the depths are finite, increase, stay apart once stored as 32-bit numbers, and are below OpendTect's undefined value
  (1e29); every value is finite and below 1e29 either way, once stored as a 32-bit number; the curve has a value;
- the well has no log of that name. A log of the same name the pack did not place is never overwritten or adopted.

What is stored differs from the LAS file in three stated ways: the empty samples at either end are not kept (OpendTect
drops them), depths and values are stored as 32-bit numbers, and OpendTect 7.0.10 sets a log's unit and mnemonic
itself (a unit it knows keeps the unit and gets that unit's mnemonic, so API becomes GR; any other unit is stored with
no unit and no mnemonic). `--compare` and the result give, per log, how many end samples were trimmed, how many depths
and values the 32-bit storage changed, with the largest change, and the unit and mnemonic given and stored.

The placing of each log is recorded before it is written and again after it is read back, so a run that stops is
completed by the next run without writing the log twice. A log the pack placed and that you delete in OpendTect is
placed again by the next run; a log edited or replaced in OpendTect is refused ("…is not the one this pack placed;
delete it in OpendTect to place it again.") and still compared, so its differences are counted; a log placed from an
earlier version of the pack's LAS file is refused until you delete it in OpendTect, then placed from the current file.

The survey must exist. OpendTect makes surveys and the connector does not: on OpendTect 7.0.10 no tool creates a
survey or a usable well without the GUI (measured: odbind opens existing surveys only and its object create adds a
database entry; `od_process_segyio` imports into an existing survey only; `od_DBMan --create` adds a database entry
with no well data behind it; `od_WellMan` only reads). Without the survey the import refuses with:

> There is no OpendTect survey at DATAROOT/SURVEY. Make it in OpendTect first (Survey > Select/Setup, then Create New
> Survey) on this pack's sampling: SAMPLING; then run the import again. Nothing was placed.

where SAMPLING is the first cube's inlines, crosslines and Z range with their steps, and the coordinate system.

### Comparing the pack in OpendTect

The maintainer qualifies the target with:

```sh
ophiolite starter opendtect pack --survey DATAROOT/SURVEY --opendtect-python /opt/OpendTect/bin/python
```

It checks the artefacts in `files/`, runs `import.py` and then `import.py --compare` in the connector's Python, and
for every placed object checks that the project's item at the pinned version holds the same bytes as the pack's file.
It writes `files/targets/opendtect/result.json` (version 2: per object, and per curve for a log, the item and version,
the OpendTect name, values, differences and moved horizon nodes, for a log its differences by kind (name, unit,
mnemonic, length, depths, empty samples, values, storage, and the inventory: missing, unexpected, duplicate, renamed,
gone from the pack), the trimmed end samples and the 32-bit changes; every object the pack placed earlier that this run
did not place, compared all the same; what was not placed, with the reason; and the total of differences), then
`starter.json` with that artefact and the oracle, each by rename. Any refusal leaves `starter.json` byte-identical.

When OpendTect holds anything other than the pack's files, the run still writes the result and the oracle, whose first
line then reads "failed: OpendTect holds something other than the pack's files (N differences); …", and `ophiolite
starter finalise` refuses with "The OpendTect import of PACK differs from the pack in N places; run ophiolite starter
opendtect again after fixing the survey." This holds for cubes and horizons as for logs, and also after an earlier
pass. A pack whose `result.json` was written by the previous version (no version field) is recognised, checked against
its oracle as before, and replaced on the next run.

Recovery (here and for `ophiolite starter python` below): the import and the comparison are run again in full every time. If a run stops (after some objects were
placed, or after `result.json` was written but before `starter.json`), run the same command again: placed objects
answer `already`, the comparison is made again, and `result.json` and `starter.json` come out byte-identical to an
uninterrupted run. A rerun after a completed run changes nothing. A `result.json` whose oracle is not the one in
`starter.json` is refused; build the pack again in a new folder. One import runs at a time per survey.

## Open a starter pack in Python on your computer

Download the pack, install `ophiolite[pack]`, set `OPHIOLITE_PACK` to the pack folder and open the notebook. It
reads the seismic and well files in the folder and draws one inline with the wells on it. It needs no network and no
Ophiolite project.

```sh
pip install "ophiolite[pack]"
export OPHIOLITE_PACK=/path/to/pack
```

The notebook is `files/targets/python/open-a-starter-pack.ipynb` in the pack; its first cell has the full install
steps. The `pack` extra installs segyio, which is LGPL-3.0; nothing else in Ophiolite uses it.

The same notebook is in the notebook gallery as "Open a starter pack". It blocks the network of its own process before it reads anything, reads the cube with segyio (its positions
from the trace headers), each 2D line with segyio trace by trace (its trace numbers, source points, positions and
samples, drawing the first), the well positions and LAS logs with lasio, and checks what it read and what it drew against
`files/targets/python/expected.json`; it stops with "Differs from expected.json: ..." naming each difference.

A pack may hold 2D lines and no cube. Its notebook then reads the wells at their own x and y (with no cube there is no
inline or crossline to place them on; `expected.json` says so in `not_computed`) and draws the first line. A pack with
lines has `expected.json` of the form `ophiolite.starter-python-expected/2`; a pack without lines keeps `/1`.

A survey archive definition may name two targets, `["opendtect", "python"]`. The Python target lists the notebook,
`expected.json` and the derived files it reads (the cube, the 2D lines, the well positions and the LAS files), at
the same paths
and with the same bytes as the OpendTect target lists them: a derived file is one artefact in every target and gets
one key. The maintainer runs the notebook on the pack with:

```sh
ophiolite starter python pack
```

It checks the artefacts, runs the packaged notebook in this Python with the network blocked (`--timeout`, default 600
seconds; `--keep DIR` keeps the notebook's working folder) and writes `files/targets/python/result.json` and then
`starter.json` with that artefact and the oracle. A failing notebook is refused with the last line of its error ("The pack
notebook did not pass: ...") and `starter.json` stays byte-identical. `finalise` refuses a pack with a Python target until this
has run.

## Open a starter pack in ResInsight

Start ResInsight 2026.09.0 with its Python server (`ResInsight --server 50061`). In a Python with the Connectors
package and its `resinsight` extra installed, run
`python PACK/files/targets/resinsight/import.py PACK PROJECT_OUT --port 50061` from any folder. It reads the pack's
well paths and logs and saves a new ResInsight project in PROJECT_OUT. The seismic cube is not imported: ResInsight's
Python API cannot import SEG-Y in this version. Nor are 2D lines: ResInsight cannot import seismic lines in this
version, and the oracle of a pack with lines says "lines: not placed". Nor are faults: this version of ResInsight
cannot import fault sticks, and the oracle of a pack with faults says "faults: not placed". Nor are time-depth
models, and the oracle of a pack with them says "Time-depth models: not placed".

```sh
pip install "arraybridge-connectors[resinsight]"
python PACK/files/targets/resinsight/import.py PACK PROJECT_OUT --port 50061
```

The ResInsight you start must have an empty project: with `--port`, the import refuses ("ResInsight on port 50061 has
an open project this launcher did not write; close it yourself or omit --port.") rather than close anything. Without
`--port`, it starts ResInsight itself (`--resinsight EXE`, or `RESINSIGHT_EXECUTABLE`) and stops it at the end.
PROJECT_OUT must be absent, empty, or a folder this import wrote for the same pack; running it again on that folder
replaces exactly the files it wrote there. It checks every pack file it reads first and refuses a changed one, and it
refuses another ResInsight or `rips` version than the 2026.09.0 and 2026.9.0.2 it was measured with.

A survey archive definition may name `["opendtect", "resinsight"]` or `["opendtect", "python", "resinsight"]`. The
ResInsight target lists `import.py` and the well positions and LAS files, at the same paths and with the same bytes as
the other targets. The maintainer imports and compares it with:

```sh
ophiolite starter resinsight pack --resinsight-python PY
```

PY (or `OPHIOLITE_RESINSIGHT_PYTHON`) is a Python with the Connectors `resinsight` extra. The command runs the pack's
`import.py` into a new temporary project, then reads every well path and log back through ResInsight, closes the
project, opens it again and reads everything a second time. Each well path is compared at ResInsight's 1 m samples
with the pack's stations interpolated in measured depth, within one float32 step; ResInsight does not expose the
stations it imported, so a station on the line through its neighbours, or a bend shorter than 1 m, is checked only in
the files the import wrote. Each LAS is compared by its curves, lengths, null values and depths and up to 50 sampled
values. With no difference, it writes `files/targets/resinsight/result.json` and then `starter.json` with the oracle;
any difference is refused ("ResInsight read the pack back with N differences; the first: ...") and nothing is written.
`finalise` refuses a pack with a ResInsight target until this has run.

## Refusals

| Exit | Meaning |
|---|---|
| 1 | Refused; the sentence names the input, decision or file and what was wrong, and says whether anything was sent |
| 3 | The access key may not add files to the project; the inputs added before it are kept in `landing.json` |
| 4 | An input has a newer version in the project than the pack was built from |
| 2 | Usage |

Without the starter extra, `build` refuses with "Install the starter extra: pip install 'ophiolite[starter]'.";
`finalise` needs no extra.

`import.py` exits 2 with one sentence when it refuses as a whole: no survey (the GUI step above), a pack file missing
or changed, another pack's folder, another import running in the survey, a write OpendTect fails, a log OpendTect
does not store as written, or the survey's record that cannot be saved (what was placed before it stays recorded).
Otherwise it does not refuse, but lists as not placed: every well path (the GUI step above), a log curve the checks
refuse (with its sentence), a depth horizon or a horizon outside the survey's grid, and a cube off the survey's
sampling. `ophiolite starter opendtect` exits 1
with the import's sentence ("The import refused: …") and leaves `starter.json` unchanged.

## What this version does not do

- It does not publish: every pack stays `unpublished: true`, and promotion comes later. A well pack's oracle says it
  compared nothing; a survey archive pack's oracle is filled by `ophiolite starter opendtect`, and its Python target's by
  `ophiolite starter python`.
- The OpendTect import does not create wells: a well path is imported in OpendTect's GUI, and a log goes only on a
  well the survey already has.
- It does not place depth horizons: the import takes time horizons only.
- A horizon with more than 100,000 nodes is not added to the project (a `failed` fidelity row); the import still
  places it in OpendTect from the pack's file, and the comparison names it as not in Ophiolite.
- It does not make the OpendTect survey: the survey must exist before the import (the GUI step above).
- It does not upload `files/` to the mirror; that is the catalogue's own step, between build and finalise.
