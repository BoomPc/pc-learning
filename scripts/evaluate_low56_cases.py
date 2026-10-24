"""Re-render nine preserved low-model cases and inspect real SVG against checked coordinates.

No model requests. The expected formulas below are independent of the page-spec expressions.
This is a local-scene regression, not a whole-question proof benchmark.
"""
import json
import math
import os
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from math_agent.rendering import render
from math_agent.storage import write_json
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/low56"


def expected(case, t):
    r = math.sqrt(3)
    values = {
        "01": {"P": [-1, 1], "Q": [3, -3]},
        "08": {"B": [0, 6], "A": [2*r, 0], "C": [0, -6], "Ap": [2*r-t, 0], "Cp": [-t, -6]},
        "16": {"A": [-1, 0], "B": [3, 0], "C": [0, 3], "P": [t, -t*t+2*t+3], "M": [t, 3-t]},
        "21": {"A": [0, 4], "B": [-4, 0], "C": [4, 0], "D": [0, 0], "M": [0, math.sqrt(2)], "N": [4-math.sqrt(2), 4]},
        "28": {"B": [-2, 3], "Bs": [2, 3], "A": [t*t+t, 3]},
        "36": {"A": [1, 0], "C": [3, -4], "D": [3, 5], "E": [23/5, 9/5]},
        "41": {"A": [0, 2], "C": [0, 0], "E": [2, 0], "D": [2, 2], "G": [2, 2], "B": [3.2, 0], "F": [4, 2]},
        "48": {"A": [0, 0], "B": [-2*r, 0], "C": [0, 2], "Bp": [-2*r*math.cos(math.radians(t)), 2*r*math.sin(math.radians(t))], "Cp": [2*math.sin(math.radians(t)), 2*math.cos(math.radians(t))]},
        "56": {"A": [0, 0], "B": [8, 0], "C": [6*math.cos(t), 6*math.sin(t)], "D": [4+3*math.cos(t), 3*math.sin(t)], "E": [2*math.cos(t), 2*math.sin(t)]},
    }
    return values[case]


def run():
    cases = []
    started = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.getenv("GGB_CHROMIUM_EXECUTABLE"))
        for case in ["01", "08", "16", "21", "28", "36", "41", "48", "56"]:
            start = time.monotonic(); folder = BASE / case
            row = {"case": case, "scope": "局部构图/关系，非整题", "model": "gpt-5.6-sol", "reasoning_effort": "low",
                   "input": "candidate.corrected.json", "model_calls_this_replay": 0, "samples": []}
            page = None
            try:
                spec = json.loads((folder / "candidate.corrected.json").read_text())
                result = render(spec, folder / "output.fixed")
                page = browser.new_page(viewport={"width": 1200, "height": 1000})
                errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(result.as_uri()); tab = spec["tabs"][0]
                svg = page.locator(".stage > svg").first
                ox, oy, scale = [float(svg.get_attribute(k)) for k in ["data-origin-x", "data-origin-y", "data-scale"]]
                slider = page.locator("input[type=range]")
                controls = tab.get("controls", {}); domain = controls.get("slider")
                samples = [0] if not domain else sorted(set([domain["min"], domain["max"], domain["default"]] +
                    [domain["min"]+(domain["max"]-domain["min"])*i/10 for i in range(11)] + controls.get("solution_targets", []) +
                    [b["value"] for b in controls.get("jump_buttons", [])]))
                for t in samples:
                    if domain:
                        slider.evaluate("(s,t)=>{s.value=t;s.dispatchEvent(new Event('input',{bubbles:true}));}", t)
                        t = float(slider.input_value())
                    points = expected(case, t)
                    actual = {}
                    for name, xy in points.items():
                        point = svg.locator(f'[data-point-name="{name}"]')
                        sx, sy = float(point.get_attribute("cx")), float(point.get_attribute("cy"))
                        assert abs(sx-(ox+xy[0]*scale)) <= .011, (case, t, name, "x", sx)
                        assert abs(sy-(oy-xy[1]*scale)) <= .011, (case, t, name, "y", sy)
                        actual[name] = [(sx-ox)/scale, (oy-sy)/scale]
                    # Inspect real line and polygon endpoints, not merely point locations.
                    lines = svg.locator(":scope > line").all()
                    if tab["stage"].get("axis", {}).get("show", True): lines = lines[2:]
                    assert len(lines) == len(tab["stage"].get("lines", []))
                    for line, definition in zip(lines, tab["stage"].get("lines", [])):
                        for index, ref in enumerate([definition["p1"], definition["p2"]], 1):
                            xy = points[ref] if isinstance(ref, str) else ref
                            assert abs(float(line.get_attribute("x"+str(index)))-(ox+xy[0]*scale)) <= .011
                            assert abs(float(line.get_attribute("y"+str(index)))-(oy-xy[1]*scale)) <= .011
                    for polygon, definition in zip(svg.locator(":scope > polygon").all(), tab["stage"].get("polygons", [])):
                        vertices = [[float(v) for v in xy.split(",")] for xy in polygon.get_attribute("points").split()]
                        assert len(vertices) == len(definition["points"])
                        for vertex, ref in zip(vertices, definition["points"]):
                            xy = points[ref] if isinstance(ref, str) else ref
                            assert abs(vertex[0]-(ox+xy[0]*scale)) <= .011 and abs(vertex[1]-(oy-xy[1]*scale)) <= .011
                    row["samples"].append({"parameter": t, "actual_math_coordinates": actual, "in_domain": slider.get_attribute("data-in-domain") if domain else None})
                for index, button in enumerate(controls.get("jump_buttons", [])):
                    page.locator(".jump-btn").nth(index).click()
                    assert abs(float(slider.input_value())-button["value"]) < 1e-10
                assert not errors, errors
                page.screenshot(path=str(folder / "output.fixed/audited-preview.png"))
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1"), "手机横向溢出"
                row["status"] = "pass"
                row["checked"] = ["实际SVG点坐标", "实际线端点", "实际多边形顶点", "答案/观察跳转", "移动视口"]
            except Exception as exc:
                row.update(status="fail", error=str(exc))
            finally:
                if page: page.close()
            row["seconds"] = round(time.monotonic()-start, 3)
            cases.append(row); write_json(BASE / "replay-results.json", {"cases": cases, "seconds": round(time.monotonic()-started, 3)})
            print(case, row["status"], row["seconds"], row.get("error", ""), flush=True)
        browser.close()
    if any(c["status"] != "pass" for c in cases): raise SystemExit(1)


if __name__ == "__main__": run()
