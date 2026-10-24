from __future__ import annotations
import json
import math
import subprocess
import sys
import time
from .config import ROOT


def definition(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


from .symbolic_geometry import PROPERTIES as SYMBOLIC_GEOMETRY_PROPERTIES

DEFINITIONS = [
    definition("symbolic_geometry", "精确计算给定坐标的旋转、平移、中点，以及距离平方、三点有向面积2倍、两向量点积、角余弦（angle_cosine的三个点中第二点为顶点）。可含实变量；不证明坐标与原题对应。", SYMBOLIC_GEOMETRY_PROPERTIES, ["points","constructions","measurements"]),
    definition("algebra_batch", "批量精确计算与解方程。分数写1/2、frac(1,2)或Rational(1,2)；只支持给定四则/幂及sqrt/abs/sin/cos/tan等白名单，不执行Python。evaluate用原表达式和substitutions核验函数代入，保留原定义域；代入值为有限实常量（可含根式/pi）。候选结果仍须核对原题范围。",
        {"operations": {"type": "array", "minItems": 1, "maxItems": 12, "items": {"type": "object", "properties": {
            "op": {"type": "string", "enum": ["simplify", "factor", "expand", "solve","evaluate"]},
            "variables": {"type": "array", "items": {"type": "string"},"description":"声明参数变量。evaluate的substitutions键也会显式声明对应变量；未赋值参数仍须列在variables中。"},
            "expression": {"type": "string"}, "substitutions":{"type":"object","additionalProperties":{"anyOf":[{"type":"number"},{"type":"string"}]}},
            "equations": {"type": "array", "items": {"type": "string"},"description":"solve只解等式（含=或表达式=0），不接受<、>等不等式；不能把不支持的查询当成已验证。"}}, "required": ["op", "variables"], "additionalProperties": False}}}, ["operations"]),
    definition("geometry_check", "核验给定数值坐标的共线、线段包含、平行、垂直、等长。只核验该实例，不能代替一般证明。",
        {"points": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
         "checks": {"type": "array", "minItems": 1, "maxItems": 40, "items": {"type": "object", "properties": {
             "relation": {"type": "string", "enum": ["collinear", "on_segment", "parallel", "perpendicular", "equal_length"]},
             "points": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 4}}, "required": ["relation", "points"], "additionalProperties": False}}}, ["points", "checks"]),
    definition("knowledge_search", "检索本地初中数学方法卡，必须核对适用条件；不是本题答案。",
        {"query": {"type": "string", "maxLength": 2000}}, ["query"]),
]


def geometry_check(points, checks, *, tolerance=1e-8):
    if not 1 <= len(points) <= 80 or not 1 <= len(checks) <= 40:
        raise ValueError("点或断言数量超限")
    for xy in points.values():
        if len(xy) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in xy):
            raise ValueError("坐标须为有限数值")
    rows = []
    for check in checks:
        relation, ids = check["relation"], check["points"]
        if len(ids) != (3 if relation in {"collinear", "on_segment"} else 4):
            raise ValueError("关系的点数不匹配")
        a, b, c, *tail = [points[n] for n in ids]
        if relation == "collinear":
            # Use the longest baseline, not an almost-zero vector between coincident points.
            pairs = [(a,b,c), (a,c,b), (b,c,a)]
            p,q,r = max(pairs, key=lambda triple: math.dist(triple[0], triple[1]))
            length = math.dist(p,q)
            if length == 0:
                rows.append({"relation":relation,"points":ids,"pass":True,"reason":"三点重合，共线但不能据此确定唯一直线"})
            else:
                distance = abs(((q[0]-p[0])/length)*(r[1]-p[1])-((q[1]-p[1])/length)*(r[0]-p[0]))
                rows.append({"relation":relation,"points":ids,"pass":distance <= tolerance*length})
            continue
        d = tail[0] if tail else a
        u = (b[0]-a[0], b[1]-a[1])
        v = (c[0]-d[0], c[1]-d[1])
        lu, lv = math.hypot(*u), math.hypot(*v)
        if lu == 0 or (tail and lv == 0):
            rows.append({"relation": relation, "points": ids, "pass": False, "reason": "退化线段不能用来证明该关系"})
            continue
        # Dimensionless tests: scaling a figure must not change its angles.
        unit_u = (u[0]/lu, u[1]/lu)
        unit_v = (v[0]/lv, v[1]/lv) if lv else (0, 0)
        cross = unit_u[0]*unit_v[1]-unit_u[1]*unit_v[0]
        dot = unit_u[0]*unit_v[0]+unit_u[1]*unit_v[1]
        eps = tolerance
        if relation in {"parallel", "collinear"}: ok = abs(cross) <= eps
        elif relation == "perpendicular": ok = abs(dot) <= eps
        elif relation == "equal_length": ok = abs(lu-lv) <= eps * max(lu, lv)
        elif relation == "on_segment":
            projection = (unit_u[0]*v[0]+unit_u[1]*v[1])/lu
            distance = abs(unit_u[0]*v[1]-unit_u[1]*v[0])
            ok = distance <= eps * max(lu, lv) and -eps <= projection <= 1+eps
        else: raise ValueError("未知几何关系")
        rows.append({"relation": relation, "points": ids, "pass": ok})
    return {"ok": all(r["pass"] for r in rows), "checks": rows,
            "scope": "浮点坐标实例校验，不是一般证明；不证明坐标忠实于原图"}


def dispatch(name, args):
    from jsonschema import validate
    definition = next((d["function"] for d in DEFINITIONS if d["function"]["name"] == name), None)
    if definition is None:
        raise ValueError("不支持此工具；模型不能执行命令或任意代码")
    try:
        validate(args, definition["parameters"])
    except Exception:
        raise ValueError("工具参数不符合声明格式") from None
    start = time.monotonic()
    try:
        result = subprocess.run([sys.executable, "-m", "math_agent.tools"], input=json.dumps({"name": name, "args": args}),
            text=True, capture_output=True, timeout=12, check=False, cwd=ROOT)
        if result.returncode or len(result.stdout) > 100000:
            return {"ok": False, "error": "计算进程失败或结果过大"}
        value = json.loads(result.stdout)
        value["seconds"] = round(time.monotonic()-start, 3)
        return value
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "计算超过12秒，已终止"}


if __name__ == "__main__":
    from . import tool_math
    from .symbolic_geometry import construct
    try:
        request = json.loads(sys.stdin.read(50000))
        funcs = {"symbolic_geometry":construct, "algebra_batch": tool_math.algebra_batch, "knowledge_search": tool_math.knowledge_search, "geometry_check": geometry_check}
        value = funcs[request["name"]](**request["args"])
    except Exception as exc:
        value = {"ok": False, "error": str(exc)[:800]}
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))
