# Starter packs

A starter pack is a small, ready-to-open set of files made from one Open Subsurface Data catalogue record: the
record's held inputs, the decisions a reader needs to interpret them, and target files made from them (for now, a
Python import script, the well heads in WGS84 and an attribution file). Its document is `osd.starter/1`;
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
`starter.json` byte-identical. The pack stays unpublished.

## Refusals

| Exit | Meaning |
|---|---|
| 1 | Refused; the sentence names the input, decision or file and what was wrong, and says whether anything was sent |
| 3 | The access key may not add files to the project; the inputs added before it are kept in `landing.json` |
| 4 | An input has a newer version in the project than the pack was built from |
| 2 | Usage |

Without the starter extra, `build` refuses with "Install the starter extra: pip install 'ophiolite[starter]'.";
`finalise` needs no extra.

## What this version does not do

- It does not publish: every pack stays `unpublished: true`. Comparing the pack with a reader outside Ophiolite (the
  oracle) and promotion come later; until then the pack's oracle says it compared nothing.
- It builds only well packs: LAS logs, well-tops CSV and deviation CSV. Seismic and horizons are not supported.
- It does not upload `files/` to the mirror; that is the catalogue's own step, between build and finalise.
