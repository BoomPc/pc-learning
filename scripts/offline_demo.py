"""Exercise the real renderer with a hand-authored fixture, without any model calls."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from math_agent.rendering import render

root = Path(__file__).resolve().parents[1]
spec = json.loads((root / "examples/demo-spec.json").read_text())
target = root / "data/offline-demo/output"
render(spec, target)
print(str(target / "result.html"))
