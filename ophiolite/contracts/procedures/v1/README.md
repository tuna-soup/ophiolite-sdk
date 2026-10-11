# Procedures, version 1 (E105a)

A procedure is a team's own code described to Ophiolite: a folder holding `procedure.json` (the manifest,
`ophiolite.procedure/1`) and the Python files it names. This folder holds its contract.

| File | What it is |
|---|---|
| `procedure-schema.json` | the structure of `procedure.json`; structure only |
| `rules.json` | `ophiolite.procedure-rules/1`: the steps, what each step may read and make (literal kind lists), units, limits and every sentence, under one `rules_version` |
| `procedure.py` | the validator of record: `validate(folder)`, `digest(folder)`, `pack(folder)`, `unpack_check(archive, destination)`; standard library only (Python 3.10) |
| `fixtures/` | valid manifests per step, single-defect invalid manifests with their expected code, field and sentence (`expected.json`), and two sample bundles |

**One validator.** The Platform and the SDK run this same `procedure.py` (the SDK's copy is byte-identical through
its contract snapshot) and the same `../../vocabulary/v1/labels.py`. Both are loaded from their source text
(`compile` + `exec` into a fresh module), so no bytecode is read or written next to them. A verdict names its
`rules_version`; the same `rules_version` gives the same verdict wherever it runs. Registration may still refuse a
valid procedure for its own reasons (E105b), in its own sentences.

**Never imported.** Validating, hashing, packing and unpacking read files only; the entry (`module:function`) is
checked against the file list (R29).

**The digest.** `sha256("ophiolite.procedure-bundle/1\n" + for each member path in sorted order: path + "\0" +
sha256-hex(bytes) + "\n")`. Members are the regular UTF-8 files of the folder, at most 200 files and 1 MiB, with
paths in one canonical spelling (`./a` and `a//b` are refused, not normalised); `__pycache__/` and `*.pyc` are not
members. File order and timestamps cannot change the digest; any byte can.

**The archive.** `pack` writes a deterministic ustar archive (sorted, mtime 0, owner 0, mode 0644, files only).
`unpack_check` refuses links, devices, unsafe or repeated names, non-text members and oversize content, and a
destination that exists and is not an empty real folder, before it writes anything.
