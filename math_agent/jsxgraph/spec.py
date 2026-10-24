"""Validate data and references; JSXGraph owns all geometric constructions."""
from __future__ import annotations
import ast
import math
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Data(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

Scalar = Union[float, str]
Pair = Annotated[list[Scalar], Field(min_length=2, max_length=2)]
Refs2 = Annotated[list[str], Field(min_length=2, max_length=2)]
class Object(Data):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
    # adapter.js fixes native labels to internal SVG text, parse=false; export
    # escapes the embedded JSON. Comparators are literal text, not HTML/code.
    label: str = Field(default="", max_length=50, description="原生SVG纯文字标签，允许数学比较符号，不解析HTML或表达式")
    source_names: list[Annotated[str,Field(min_length=1,max_length=500)]] = Field(default_factory=list,max_length=12,
        description="不显示的原文对象绑定名。曲线的id/label不能对应source.native_constructions.parents时，把该原文名称逐字填入此数组；label仍可显示简洁公式。名称绑定不证明曲线公式正确。")
    color: str = Field(default="#65c7ff", pattern=r"^#[0-9a-fA-F]{6}$")
    visible: bool = True
    dashed: bool = False

class Point(Object):
    kind: Literal["point"]
    coords: Pair
class TwoPoints(Object):
    kind: Literal["line", "segment", "midpoint"]
    parents: Refs2
class LinePoint(Object):
    kind: Literal["parallel", "perpendicular", "perpendicularpoint", "reflection"]
    parents: Refs2
class Intersection(Object):
    kind: Literal["intersection"]
    parents: Refs2
    branch: Literal[0, 1]
class Rotation(Object):
    kind: Literal["rotation"]
    parents: Refs2
    angle: Scalar | None = Field(default=None, description="旧格式有符号弧度；新构图使用direction和degrees，二者不得混用")
    direction: Literal['clockwise', 'counterclockwise'] | None = None
    degrees: Scalar | None = Field(default=None, description="非负角度大小，单位度；方向单独填写，可用非负t表达式")

    @model_validator(mode='after')
    def rotation_units(self):
        if self.angle is not None:
            if self.direction is not None or self.degrees is not None:
                raise ValueError('rotation不能混用angle与direction/degrees')
        elif self.direction is None or self.degrees is None:
            raise ValueError('rotation须同时填写direction与degrees；或仅使用旧angle')
        if isinstance(self.degrees,(int,float)) and self.degrees < 0:
            raise ValueError('degrees必须非负，顺逆时针由direction决定')
        return self
class Translation(Object):
    kind: Literal["translation"]
    parents: Annotated[list[str], Field(min_length=1, max_length=1)]
    vector: Pair
class Circle(Object):
    kind: Literal["circle"]
    parents: Annotated[list[str], Field(min_length=1, max_length=2)]
    radius: Scalar | None = None
class Polygon(Object):
    kind: Literal["polygon"]
    parents: Annotated[list[str], Field(min_length=3, max_length=30)]
class Angle(Object):
    kind: Literal["angle"]
    parents: Annotated[list[str], Field(min_length=3, max_length=3)]
class Function(Object):
    kind: Literal["functiongraph"]
    expression: Scalar
    domain: Annotated[list[float], Field(min_length=2, max_length=2)]
class Glider(Object):
    kind: Literal["glider"]
    parents: Annotated[list[str], Field(min_length=1, max_length=1)]
    coords: Annotated[list[float], Field(min_length=2, max_length=2)]

Geometry = Annotated[Union[Point, TwoPoints, LinePoint, Intersection, Rotation, Translation, Circle, Polygon, Angle, Function, Glider], Field(discriminator="kind")]
class View(Data):
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    @model_validator(mode='after')
    def ordered(self):
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError('view必须满足x_min<x_max且y_min<y_max；不得自动交换坐标')
        return self

    def box(self):
        return [self.x_min,self.y_max,self.x_max,self.y_min]


class Board(Data):
    view: View | None = Field(default=None,description='优先使用具名横纵坐标范围；不能与bounding_box同时提供')
    bounding_box: Annotated[list[float], Field(min_length=4, max_length=4,
        description="数学视野依次为[左界x_min,上界y_max,右界x_max,下界y_min]，左<右且上>下，例如[-5,5,5,-5]；不是[x_min,x_max,y_min,y_max]")] | None = None
    viewport: Literal['manual','fit_points'] = Field(default='manual', description="fit_points按当前可见原生点自适应视野，可省略bounding_box；不改变几何或参数域，不保证无限曲线完整显示")
    axis: bool = True
    objects: Annotated[list[Geometry], Field(min_length=1, max_length=120)]

    @model_validator(mode='after')
    def viewport_settings(self):
        if self.view is not None:
            if self.bounding_box is not None:
                raise ValueError('view和bounding_box只能提供一种，不能猜测冲突范围')
            self.bounding_box = self.view.box()
            self.view = None
        if self.viewport=='manual' and self.bounding_box is None:
            raise ValueError('manual视野必须提供bounding_box；自动视野使用viewport=fit_points')
        return self
class Slider(Data):
    min: float
    max: float
    default: float
    step: float = Field(default=.01, gt=0)
    label: str = Field(default="参数 t", max_length=80)
    min_inclusive: bool = True
    max_inclusive: bool = True
class Jump(Data):
    text: str = Field(min_length=1, max_length=100)
    value: float
    is_target: bool = False
class Controls(Data):
    slider: Slider
    solution_targets: list[float] = Field(default_factory=list, max_length=30)
    jump_buttons: list[Jump] = Field(default_factory=list, max_length=30)
class Step(Data):
    head: str = Field(min_length=1, max_length=4000)
    content: str = Field(min_length=1, max_length=15000)
class Tab(Data):
    tab_title: str = Field(min_length=1, max_length=100)
    board: Board
    controls: Controls | None = None
    steps: list[Step] = Field(min_length=1, max_length=50)
    conclusion: str = Field(min_length=1, max_length=4000)
class Page(Data):
    format: Literal["jsxgraph-v1"]
    title: str = Field(min_length=1, max_length=100)
    problem_text: str = Field(min_length=1, max_length=20000)
    tabs: list[Tab] = Field(min_length=1, max_length=12)

POINTS = {"point", "midpoint", "intersection", "perpendicularpoint", "reflection", "rotation", "translation", "glider"}
LINES = {"line", "segment", "parallel", "perpendicular"}
CURVES = LINES | {"circle", "functiongraph"}
FUNCTIONS = {"sin": (1, 1), "cos": (1, 1), "tan": (1, 1), "sqrt": (1, 1), "abs": (1, 1), "min": (2, 8), "max": (2, 8)}
OPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Pow: "pow", ast.Mod: "mod"}

def expression(value, allowed):
    """A small arithmetic data tree, never model-supplied JS or eval."""
    if isinstance(value, (int, float)):
        if not math.isfinite(value): raise ValueError("非有限表达式")
        return value
    if len(value) > 600: raise ValueError("表达式过长")
    root = ast.parse(value.replace("^", "**"), mode="eval").body
    if len(list(ast.walk(root))) > 120: raise ValueError("表达式过于复杂")
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float) and math.isfinite(n.value): return n.value
        if isinstance(n, ast.Name):
            if n.id == "pi": return math.pi
            if n.id in allowed: return ["var", n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return ["neg" if isinstance(n.op, ast.USub) else "pos", visit(n.operand)]
        if isinstance(n, ast.BinOp) and type(n.op) in OPS: return [OPS[type(n.op)], visit(n.left), visit(n.right)]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCTIONS and not n.keywords:
            lo, hi = FUNCTIONS[n.func.id]
            if lo <= len(n.args) <= hi: return [n.func.id, *[visit(a) for a in n.args]]
        raise ValueError("不支持的表达式；只允许算术、pi、t、曲线变量 x 和指定数学函数")
    return visit(root)

def validate(raw):
    page = Page.model_validate(raw).model_dump(exclude_none=True)
    for tab in page["tabs"]:
        box = tab['board'].setdefault('bounding_box',[-5.,5.,5.,-5.])
        if not (box[0] < box[2] and box[1] > box[3]):
            raise ValueError(f"{tab['tab_title']}.bounding_box={box!r} 须为左、上、右、下；左<右且上>下，不得按[x_min,x_max,y_min,y_max]排列；请根据真实图形明确修正，不自动交换坐标")
        objects = tab["board"]["objects"]
        by_id = {o["id"]: o for o in objects}
        if len(by_id) != len(objects): raise ValueError("对象编号重复")
        dynamic = "controls" in tab
        allowed = {"t"} if dynamic else set()
        for o in objects:
            # The absent default is semantically identical to []; preserve old
            # scene fingerprints, while nonempty source bindings stay hashed.
            if not o.get('source_names'):o.pop('source_names',None)
            refs, kind = o.get("parents", []), o["kind"]
            if any(r not in by_id for r in refs): raise ValueError("引用未声明对象：" + o["id"])
            kinds = [by_id[r]["kind"] for r in refs]
            expected = None
            if kind in {"line", "segment", "midpoint", "rotation", "polygon", "circle", "angle", "translation"}: expected = [POINTS]*len(refs)
            elif kind in {"parallel", "perpendicular"}: expected = [LINES, POINTS]
            elif kind in {"perpendicularpoint", "reflection"}: expected = [POINTS, LINES]
            elif kind == "intersection": expected = [CURVES, CURVES]
            elif kind == "glider": expected = [CURVES]
            if expected and any(k not in group for k, group in zip(kinds, expected)): raise ValueError("父对象类型或顺序不匹配：" + o["id"])
            if kind == "circle" and ((len(refs) == 1) != ("radius" in o)): raise ValueError("圆需圆心+半径，或圆心+圆上点")
            if kind == "functiongraph" and o["domain"][0] >= o["domain"][1]: raise ValueError("函数区间无效")
            for field in ("coords", "vector", "angle", "degrees", "radius", "expression"):
                if field in o:
                    vals = o[field] if isinstance(o[field], list) else [o[field]]
                    for v in vals: expression(v, allowed | ({"x"} if field == "expression" else set()))
        visiting, done, ordered = set(), set(), []
        def visit(name):
            if name in visiting: raise ValueError("对象存在循环依赖：" + name)
            if name in done: return
            visiting.add(name)
            for ref in by_id[name].get("parents", []): visit(ref)
            visiting.remove(name); done.add(name); ordered.append(by_id[name])
        for name in by_id: visit(name)
        tab["board"]["objects"] = ordered
        if dynamic:
            controls = tab["controls"]; s = controls["slider"]
            if not (s["min"] < s["max"] and s["min"] <= s["default"] <= s["max"]): raise ValueError("滑块范围无效")
            values = controls["solution_targets"] + [b["value"] for b in controls["jump_buttons"]]
            if any(not s["min"] <= v <= s["max"] for v in values): raise ValueError("跳转超出范围")
            targets = controls["solution_targets"] + [b["value"] for b in controls["jump_buttons"] if b["is_target"]]
            if any((v == s["min"] and not s["min_inclusive"]) or (v == s["max"] and not s["max_inclusive"]) for v in targets): raise ValueError("题设不包含的端点不能标为答案")
    return page

def compile_page(page):
    import copy
    result = copy.deepcopy(page)
    for tab in result["tabs"]:
        allowed = {"t"} if "controls" in tab else set()
        for o in tab["board"]["objects"]:
            for field in ("coords", "vector", "angle", "degrees", "radius", "expression"):
                if field in o and o["kind"] != "glider":
                    vars = allowed | ({"x"} if field == "expression" else set())
                    o[field] = [expression(v, vars) for v in o[field]] if field in {"coords", "vector"} else expression(o[field], vars)
    return result
