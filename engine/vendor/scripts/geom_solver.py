"""
中考解析几何与动点温控核心解算工具库 (geom_solver.py)
专为大模型前置几何验算提供开箱即用的高精度数学计算与采样能力，
杜绝模型从头编写一次性解析几何脚本的语法调试耗时。
"""

import math
from typing import Tuple, List, Optional, Dict, Any

def solve_parabola_3pts(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float]) -> Dict[str, Any]:
    """通过不在同一直线上的三点精确求解二次函数 y = ax^2 + bx + c 及顶点、对称轴"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    denom = (x1 - x2) * (x1 - x3) * (x2 - x3)
    if abs(denom) < 1e-9:
        raise ValueError("三点共线或存在相同横坐标，无法确定二次函数")
    
    a = (x3 * (y2 - y1) + x2 * (y1 - y3) + x1 * (y3 - y2)) / denom
    b = (x3**2 * (y1 - y2) + x2**2 * (y3 - y1) + x1**2 * (y2 - y3)) / denom
    c = (x2 * x3 * (x2 - x3) * y1 + x3 * x1 * (x3 - x1) * y2 + x1 * x2 * (x1 - x2) * y3) / denom
    
    axis_x = -b / (2 * a)
    vertex_y = (4 * a * c - b**2) / (4 * a)
    
    return {
        "a": round(a, 6),
        "b": round(b, 6),
        "c": round(c, 6),
        "axis_x": round(axis_x, 6),
        "vertex": (round(axis_x, 6), round(vertex_y, 6)),
        "expr_str": f"{round(a, 4)}*x**2 + {round(b, 4)}*x + {round(c, 4)}"
    }

def solve_parabola_vertex(vertex: Tuple[float, float], p: Tuple[float, float]) -> Dict[str, Any]:
    """通过顶点 (h, k) 及另一点求解抛物线 y = a(x-h)^2 + k"""
    h, k = vertex
    x, y = p
    if abs(x - h) < 1e-9:
        raise ValueError("已知点与顶点横坐标重合，无法确定抛物线")
    a = (y - k) / ((x - h)**2)
    b = -2 * a * h
    c = a * h**2 + k
    return {
        "a": round(a, 6),
        "b": round(b, 6),
        "c": round(c, 6),
        "axis_x": round(h, 6),
        "vertex": (round(h, 6), round(k, 6)),
        "expr_str": f"{round(a, 4)}*x**2 + {round(b, 4)}*x + {round(c, 4)}"
    }

def line_from_points(p1: Tuple[float, float], p2: Tuple[float, float]) -> Dict[str, Any]:
    """通过两点求解一次函数 y = kx + b"""
    x1, y1 = p1
    x2, y2 = p2
    if abs(x1 - x2) < 1e-9:
        return {"vertical": True, "x": round(x1, 6), "k": None, "b": None}
    k = (y2 - y1) / (x2 - x1)
    b = y1 - k * x1
    return {"vertical": False, "k": round(k, 6), "b": round(b, 6), "expr_str": f"{round(k, 4)}*x + {round(b, 4)}"}

def line_intersection(l1: Dict[str, Any], l2: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """求解两条直线的精确交点坐标"""
    v1, v2 = l1.get("vertical", False), l2.get("vertical", False)
    if v1 and v2:
        return None
    if v1:
        x = l1["x"]
        y = l2["k"] * x + l2["b"]
        return (round(x, 6), round(y, 6))
    if v2:
        x = l2["x"]
        y = l1["k"] * x + l1["b"]
        return (round(x, 6), round(y, 6))
    k1, b1 = l1["k"], l1["b"]
    k2, b2 = l2["k"], l2["b"]
    if abs(k1 - k2) < 1e-9:
        return None  # 平行无交点
    x = (b2 - b1) / (k1 - k2)
    y = k1 * x + b1
    return (round(x, 6), round(y, 6))

def distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """两点间欧式距离"""
    return round(math.hypot(p1[0] - p2[0], p1[1] - p2[1]), 6)

def midpoint(p1: Tuple[float, float], p2: Tuple[float, float]) -> Tuple[float, float]:
    """线段中点坐标"""
    return (round((p1[0] + p2[0]) / 2, 6), round((p1[1] + p2[1]) / 2, 6))

def divide_point(p1: Tuple[float, float], p2: Tuple[float, float], t: float) -> Tuple[float, float]:
    """
    定比内分点计算: P = p1 + t * (p2 - p1)
    t = 0 时为 p1, t = 1 时为 p2, t = 0.5 时为中点
    """
    x = p1[0] + t * (p2[0] - p1[0])
    y = p1[1] + t * (p2[1] - p1[1])
    return (round(x, 6), round(y, 6))

def triangle_shoelace_area(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float]) -> float:
    """任意三角形面积 (初中几何割补法等价实现)"""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    area = 0.5 * abs(x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    return round(area, 6)

def triangle_vertical_height_area(p_top: Tuple[float, float], p_bot: Tuple[float, float], x_left: float, x_right: float) -> float:
    """初中铅垂高割补法计算三角形面积 S = 1/2 * h * (x_right - x_left)"""
    h = abs(p_top[1] - p_bot[1])
    base_x = abs(x_right - x_left)
    return round(0.5 * h * base_x, 6)

def rotate_point(p: Tuple[float, float], center: Tuple[float, float], angle_deg: float) -> Tuple[float, float]:
    """点绕中心逆时针旋转指定度数"""
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    dx = p[0] - center[0]
    dy = p[1] - center[1]
    rx = center[0] + dx * cos_a - dy * sin_a
    ry = center[1] + dx * sin_a + dy * cos_a
    return (round(rx, 6), round(ry, 6))

def reflect_point(p: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float]) -> Tuple[float, float]:
    """点 p 关于直线 p1-p2 的轴对称（翻折）点"""
    x0, y0 = p
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if denom < 1e-12:
        raise ValueError("线段端点重合，无法确定对称轴")
    t = ((x0 - x1) * dx + (y0 - y1) * dy) / denom
    hx = x1 + t * dx
    hy = y1 + t * dy
    rx = 2 * hx - x0
    ry = 2 * hy - y0
    return (round(rx, 6), round(ry, 6))

def get_temp_color(current_val: float, target_val: float, tol_orange: float = 0.45, tol_green: float = 0.035) -> str:
    """
    三阶温控探索动态反馈色值生成:
    - 偏差极小 (< tol_green): 荧光绿 #4ade80 (命中答案)
    - 临近目标 (< tol_orange): 琥珀橙 #f59e0b (接近目标)
    - 远离目标: 探索珊瑚红 #f87171 (偏离目标)
    """
    diff = abs(current_val - target_val)
    if diff <= tol_green:
        return "#4ade80"
    elif diff <= tol_orange:
        return "#f59e0b"
    else:
        return "#f87171"

# ==================== 铁闸二：前置几何硬断言工具函数 ====================

def assert_point_in_box(p: Tuple[float, float], x_min: float, x_max: float, y_min: float, y_max: float, name: str = "点"):
    """断言点坐标在指定的包围盒区间内，杜绝坐标飞出画布"""
    x, y = p
    assert x_min - 1e-4 <= x <= x_max + 1e-4, f"【熔断阻断】{name} 的横坐标 x={x} 超出预期范围 [{x_min}, {x_max}]！"
    assert y_min - 1e-4 <= y <= y_max + 1e-4, f"【熔断阻断】{name} 的纵坐标 y={y} 超出预期范围 [{y_min}, {y_max}]！"

def assert_point_on_segment(p: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], tol: float = 1e-3, name: str = "点"):
    """断言点在线段 p1-p2 内部，杜绝点位在线段外或脱轨"""
    x, y = p
    min_x, max_x = min(p1[0], p2[0]), max(p1[0], p2[0])
    min_y, max_y = min(p1[1], p2[1]), max(p1[1], p2[1])
    assert min_x - tol <= x <= max_x + tol, f"【熔断阻断】{name}({x:.2f}, {y:.2f}) 未在线段 x 区间 [{min_x:.2f}, {max_x:.2f}] 内！"
    assert min_y - tol <= y <= max_y + tol, f"【熔断阻断】{name}({x:.2f}, {y:.2f}) 未在线段 y 区间 [{min_y:.2f}, {max_y:.2f}] 内！"
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    line_len = math.hypot(dx, dy)
    if line_len > 1e-9:
        dist_to_line = abs(dy * x - dx * y + p2[0] * p1[1] - p2[1] * p1[0]) / line_len
        assert dist_to_line <= tol, f"【熔断阻断】{name}({x:.2f}, {y:.2f}) 偏离目标直线，距离为 {dist_to_line:.4f} > {tol}！"

def assert_angle_equal(p_ray1: Tuple[float, float], vertex: Tuple[float, float], p_ray2: Tuple[float, float], target_deg: float, tol_deg: float = 0.15, name: str = "角"):
    """断言两射线形成的夹角等于给定目标度数，杜绝方向角算反"""
    v1 = (p_ray1[0] - vertex[0], p_ray1[1] - vertex[1])
    v2 = (p_ray2[0] - vertex[0], p_ray2[1] - vertex[1])
    len1 = math.hypot(*v1)
    len2 = math.hypot(*v2)
    assert len1 > 1e-9 and len2 > 1e-9, f"【熔断阻断】{name} 的射线端点与顶点重合，无法计算角度！"
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    cos_val = max(-1.0, min(1.0, dot / (len1 * len2)))
    actual_deg = math.degrees(math.acos(cos_val))
    assert abs(actual_deg - target_deg) <= tol_deg, f"【熔断阻断】{name} 实际角度为 {actual_deg:.2f}°，与目标 {target_deg}° 偏差过大！(可能方向角算反)"

def assert_length_equal(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float], p4: Tuple[float, float], tol: float = 1e-3, name: str = "线段"):
    """断言线段 p1p2 与 p3p4 长度相等"""
    len1 = distance(p1, p2)
    len2 = distance(p3, p4)
    assert abs(len1 - len2) <= tol, f"【熔断阻断】{name} 长度不相等: len1={len1:.4f}, len2={len2:.4f}，误差={abs(len1-len2):.4f} > {tol}！"

def assert_perpendicular(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float], p4: Tuple[float, float], tol: float = 1e-3, name: str = "垂直关系"):
    """断言直线 p1p2 与 p3p4 相互垂直"""
    dx1, dy1 = p2[0] - p1[0], p2[1] - p1[1]
    dx2, dy2 = p4[0] - p3[0], p4[1] - p3[1]
    l1, l2 = math.hypot(dx1, dy1), math.hypot(dx2, dy2)
    assert l1 > 1e-9 and l2 > 1e-9, f"【熔断阻断】{name} 的线段端点重合！"
    dot = (dx1 * dx2 + dy1 * dy2) / (l1 * l2)
    assert abs(dot) <= tol, f"【熔断阻断】{name} 夹角不是 90° (dot={dot:.4f} > {tol})！"

def assert_parallel(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float], p4: Tuple[float, float], tol: float = 1e-3, name: str = "平行关系"):
    """断言直线 p1p2 与 p3p4 相互平行"""
    dx1, dy1 = p2[0] - p1[0], p2[1] - p1[1]
    dx2, dy2 = p4[0] - p3[0], p4[1] - p3[1]
    l1, l2 = math.hypot(dx1, dy1), math.hypot(dx2, dy2)
    assert l1 > 1e-9 and l2 > 1e-9, f"【熔断阻断】{name} 的线段端点重合！"
    cross = abs(dx1 * dy2 - dy1 * dx2) / (l1 * l2)
    assert cross <= tol, f"【熔断阻断】{name} 两直线不平行 (cross={cross:.4f} > {tol})！"

def assert_collinear(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float], tol: float = 1e-3, name: str = "三点共线"):
    """断言 p1, p2, p3 三点共线"""
    area = triangle_shoelace_area(p1, p2, p3)
    assert area <= tol, f"【熔断阻断】{name} 不共线，所围三角形面积 S={area:.4f} > {tol}！"

def assert_tangent(center: Tuple[float, float], radius: float, p1: Tuple[float, float], p2: Tuple[float, float], tol: float = 1e-3, name: str = "切线关系"):
    """断言直线 p1p2 与圆心为 center、半径为 radius 的圆相切"""
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    line_len = math.hypot(dx, dy)
    assert line_len > 1e-9, f"【熔断阻断】{name} 的切线端点重合！"
    dist = abs(dy * center[0] - dx * center[1] + p2[0] * p1[1] - p2[1] * p1[0]) / line_len
    assert abs(dist - radius) <= tol, f"【熔断阻断】{name} 不相切: 圆心到直线距离={dist:.4f}, 半径={radius:.4f}, 误差={abs(dist-radius):.4f} > {tol}！"

def auto_fit_viewbox(points: List[Tuple[float, float]], viewbox_size: Tuple[int, int] = (560, 420), margin: float = 48) -> Dict[str, Any]:
    """
    根据几何关键点列表自动计算最佳 origin 与 scale，
    保证全部几何图元 100% 居中且安全在轨落在画布内部，永不触发视口熔断阻断。
    """
    if not points:
        return {"origin": [145, 325], "scale": 60, "viewBox": f"0 0 {viewbox_size[0]} {viewbox_size[1]}"}
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    avail_w = viewbox_size[0] - 2 * margin
    avail_h = viewbox_size[1] - 2 * margin
    scale = min(avail_w / span_x, avail_h / span_y)
    scale = max(20.0, min(scale, 120.0))
    scale = round(scale, 1)
    center_math_x = (min_x + max_x) / 2
    center_math_y = (min_y + max_y) / 2
    center_screen_x = viewbox_size[0] / 2
    center_screen_y = viewbox_size[1] / 2
    ox = round(center_screen_x - center_math_x * scale, 1)
    oy = round(center_screen_y + center_math_y * scale, 1)
    return {
        "origin": [ox, oy],
        "scale": scale,
        "viewBox": f"0 0 {viewbox_size[0]} {viewbox_size[1]}"
    }


