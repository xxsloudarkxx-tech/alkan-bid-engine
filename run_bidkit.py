"""Run this checkout explicitly, even if another bidkit is installed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from bidkit.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
