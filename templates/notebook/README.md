# Read and plot an exact curve

Preview template version **0.1.0**. Compare `template_version` with the SDK
CHANGELOG before upgrading. Keep `../support.py` alongside this directory.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
make dev
# In a separate terminal using the same virtual environment:
make test
```

The default development command uses only the original synthetic loopback fixture.
No customer service, credential or data source is needed. The five-sample curve
contains zero and a missing sample; units and depth reference remain explicit.
The included sonic/density file is additional synthetic example data, not an
automatically converted second source.

`make dev` starts the synthetic fixture and Jupyter on loopback. Open the printed
Jupyter URL and run `read-and-plot.ipynb`. The notebook displays a separate scientific
descriptor and saves `curve.png`. It shows deliberate incompatible-axis and expired
credential guidance. The paired percent script is the source; regenerate with
`python ../../tools/build_notebook.py`. Do not commit executed outputs containing
customer data. The tests execute the actual notebook with nbclient.

## Live mode and recovery

Set `OPHIOLITE_URL` and `OPHIOLITE_PROJECT`, sign in with `ophiolite login` and
use `make live`. Optional `OPHIOLITE_CREDENTIAL` selects an explicit private SDK
credential file. Do not put credentials in the configuration example. The example
expects a permitted gamma-ray curve; adapt the selection explicitly for your data.

Expired credential: run `ophiolite login`. Revoked access: ask the owner to check
permissions. Different axes/units: read separately or align explicitly. Capacity
refusal: select a smaller input. Changed input: read and verify the exact version
again. Invalid names, source-curve collisions and the LAS missing marker refuse
locally. A lost publication reply needs the original work folder. An uncertain
share needs a grants read first; this template does not automatically repeat it.

No production support, live identity-provider qualification, automatic conversion
or synchronisation is claimed by these synthetic examples.
