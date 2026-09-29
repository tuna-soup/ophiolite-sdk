"""Small scientific application using the public SDK only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from support import command

if __name__=='__main__': raise SystemExit(command())
