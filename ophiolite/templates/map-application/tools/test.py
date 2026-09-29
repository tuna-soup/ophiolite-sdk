"""Required synthetic template lane; any failed child fails this command."""
import os
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
env=dict(os.environ,OPHIOLITE_PYTHON=sys.executable)
for command in [[sys.executable,'-m','pytest','-q','tests/test_server.py'],['npm','run','build'],['npm','test'],['node','tests/smoke.mjs']]:
    subprocess.run(command,cwd=root,env=env,check=True)
