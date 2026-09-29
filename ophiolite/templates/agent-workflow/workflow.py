"""Agent recipe: discover, read exact input, validate, calculate, publish, recover."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from support import command, workflow

if __name__=='__main__': raise SystemExit(command())
