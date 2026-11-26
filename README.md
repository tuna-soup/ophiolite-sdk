# Ophiolite SDK

Ophiolite keeps subsurface data (well logs, tops, surveys and surfaces) as exact versions with their sources; this SDK reads, checks and publishes them from Python and the `ophiolite` command.

## Install

<!-- not-run: the test installs the candidate wheel in its place -->
```sh
python -m pip install 'ophiolite==<release>'
```

This installs the SDK from PyPI once a release is published; Python 3.10 or later is required.

## Try it on this computer

```sh
ophiolite demo --bundle f3-block.zip
```

This serves the F3-block bundle (public NLOG wells, logs, surveys and tops of the Dutch F3 block, and TNO DGM-deep horizons via NLOG) on this computer and prints three commands to run on it.
The bundle is not yet downloadable; it will be once it is published.
For the F3-block bundle the three commands list the wells, fetch one well's whole gamma-ray curve into a new folder, and double a gamma-ray curve and publish the result with the derive-and-publish template:

<!-- not-run: these are the F3 bundle's lines (its asset and revision); hosted CI runs the lines the demo prints, and the lane-host run runs this block verbatim -->
```sh
ophiolite data wells list --configuration ophiolite-demo/configuration.json --credentials ophiolite-demo/credential.json
ophiolite data fetch --asset e466c261fde739e51375ec32ec319a04ba3662eec0074bae0bf6d9745ae2d480 --revision 7d0d2c08d1c270d131cb4e0989953328fdbd5a3bd9f61c114dca5bb421bbe906 --curve GR --output ophiolite-demo/F02-01-GR --configuration ophiolite-demo/configuration.json --credentials ophiolite-demo/credential.json
python ophiolite-demo/derive-and-publish/app --configuration ophiolite-demo/configuration.json --credentials ophiolite-demo/credential.json --work ophiolite-demo/work
```

The same demo from Python: the wells, and the gamma-ray curve of the first log.

```python
from ophiolite import Client, Credential

credential = Credential.from_file('ophiolite-demo/credential.json')
with Client.from_configuration('ophiolite-demo/configuration.json', credential=credential) as client:
    wells = client.wells()
    log = next(item for item in client.assets() if 'GR' in item['curves'])
    gr = client.read(log['asset_id'], log['revision'], ['GR']).curves[0]
    print(f'{len(wells)} wells, the first {wells[0].name}; GR of the first log: {len(gr.values)} samples, {gr.axis[0]} to {gr.axis[-1]}')
```

Stop the demo; its publications end with it:

```sh
ophiolite demo stop
```

## Where to go

- [The documentation](https://ophiolite.dev/docs/) and [the SDK guide](https://github.com/ophiolite-labs/ophiolite-sdk/blob/main/docs/sdk-guide.md).
- [Run Ophiolite on your own host](https://ophiolite.dev/docs/operate/install/) and [try it there](https://ophiolite.dev/docs/try/next/).
- Against a real deployment, sign in with `ophiolite account login` and never put a credential in source files or logs ([sign-in](https://ophiolite.dev/docs/guides/sign-in/)).
- [Licence: Apache-2.0](https://github.com/ophiolite-labs/ophiolite-sdk/blob/main/LICENSE).

Stability, compatibility and qualification statements: [CONTRACTS.md](https://github.com/ophiolite-labs/ophiolite-sdk/blob/main/CONTRACTS.md).
