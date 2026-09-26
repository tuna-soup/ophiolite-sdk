"""Run Jupyter and the explicitly synthetic fixture on loopback."""
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from support import synthetic_server
with synthetic_server() as server:
    env=dict(os.environ,OPHIOLITE_URL=server.url,OPHIOLITE_PROJECT='p',OPHIOLITE_TEMPLATE_FIXTURE='1',OPHIOLITE_TEMPLATES_ROOT=str(Path(__file__).resolve().parents[1]))
    raise SystemExit(subprocess.call([sys.executable,'-m','jupyterlab','--ip=127.0.0.1','--no-browser','read-and-plot.ipynb'],env=env))
