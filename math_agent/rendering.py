from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
from .config import ROOT


class RenderError(ValueError):
    pass


def render(spec, directory: Path, *, validate_only=False):
    from .storage import write_json
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "spec.json", spec)
    args = [sys.executable, "-m", "math_agent.rendering", str(directory), "validate" if validate_only else "export"]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=75, cwd=ROOT)
    except subprocess.TimeoutExpired:
        raise RenderError("网页校验或渲染超时") from None
    if result.returncode:
        # Only controlled last error record; never return a full environment/traceback.
        raise RenderError(result.stderr.strip()[-2500:] or "渲染进程异常退出")
    return directory / "result.html"


def strict_spec(raw):
    from .jsxgraph.spec import validate
    return validate(raw)


def main():
    directory = Path(sys.argv[1]).resolve()
    try:
        spec = strict_spec(json.loads((directory / "spec.json").read_text()))
        if sys.argv[2] == "validate": return
        from .jsxgraph.export import export
        export(spec, directory)
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc)[:2200], file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__": main()
