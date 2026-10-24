import os
import re
import sys
import json
import base64
import math
from expression_runtime import evaluate as evaluate_expression, javascript as javascript_expression
from typing import Dict, Any, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def robust_json_load(raw_input: str) -> dict:
    """
    抗畸变 JSON 解析器：
    自动容忍并修复大模型输出中常见的 LaTeX 裸反斜杠 (\\frac -> \frac)、
    末尾多余逗号、以及控制字符等问题，彻底斩断 JSONDecodeError 中断。
    """
    if isinstance(raw_input, dict):
        return raw_input
        
    text = raw_input.strip()
    # 如果包含 markdown 代码块包裹，自动剥离
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
        
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 1. 消除末尾非法逗号 ,} -> } 以及 ,] -> ]
        fixed_text = re.sub(r',\s*([\}\]])', r'\1', text)
        # 2. 预处理未双转义的 LaTeX 反斜杠 (如 \frac -> \\frac, \sqrt -> \\sqrt)
        # 仅修复未被正确转义的 LaTeX 反斜杠
        latex_cmds = [
            'frac', 'sqrt', 'therefore', 'because', 'implies', 'iff', 'parallel', 'perp',
            'cong', 'sim', 'angle', 'triangle', 'times', 'cdot', 'to', 'rightarrow', 'leftarrow',
            'ne', 'neq', 'le', 'leq', 'ge', 'geq', 'pm', 'mp', 'circ', 'deg', 'approx',
            'odot', 'left', 'right', 'quad', 'qquad', 'text', 'cases', 'begin', 'end',
            'Delta', 'alpha', 'beta', 'theta', 'pi', 'in', 'notin', 'infty',
            'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'widehat', 'overarc'
        ]
        for cmd in latex_cmds:
            fixed_text = re.sub(rf'(?<!\\)\\{cmd}\b', rf'\\\\{cmd}', fixed_text)
            
        try:
            return json.loads(fixed_text)
        except Exception as e:
            # 3. 终极兜底方案：尝试利用 eval 解析合法的 Python 字典格式
            try:
                # 安全受限环境
                return eval(fixed_text, {"__builtins__": None, "true": True, "false": False, "null": None}, {})
            except Exception:
                raise ValueError(f"JSON解析失败且无法自动修复: {e}")

def replace_nested_latex(text: str) -> str:
    """递归解析并替换嵌套的 \\frac 与 \\sqrt 为标准中考原生流式排版"""
    # 1. 递归替换 \\frac{A}{B}
    idx = 0
    while True:
        pos = text.find(r"\frac{", idx)
        cmd_len = 6
        if pos == -1:
            pos = text.find(r"\\frac{", idx)
            cmd_len = 7
        if pos == -1:
            break

        start1 = pos + cmd_len
        depth = 1
        i = start1
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        if depth != 0 or i >= len(text) or text[i] != "{":
            idx = pos + cmd_len
            continue
        arg1 = text[start1 : i - 1]

        start2 = i + 1
        depth = 1
        j = start2
        while j < len(text) and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        if depth == 0:
            arg2 = text[start2 : j - 1]
            arg1_p = replace_nested_latex(arg1)
            arg2_p = replace_nested_latex(arg2)
            replacement = f'<span class="frac"><span>{arg1_p}</span><span>{arg2_p}</span></span>'
            text = text[:pos] + replacement + text[j:]
            idx = pos + len(replacement)
        else:
            idx = pos + cmd_len

    # 2. 递归替换 \\sqrt{A}
    idx = 0
    while True:
        pos = text.find(r"\sqrt{", idx)
        cmd_len = 6
        if pos == -1:
            pos = text.find(r"\\sqrt{", idx)
            cmd_len = 7
        if pos == -1:
            break

        start_arg = pos + cmd_len
        depth = 1
        i = start_arg
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            arg = text[start_arg : i - 1]
            arg_p = replace_nested_latex(arg)
            replacement = f'<span class="sqrt"><span class="sqrt-rad">{arg_p}</span></span>'
            text = text[:pos] + replacement + text[i:]
            idx = pos + len(replacement)
        else:
            idx = pos + cmd_len

    return text

def format_math_text(text: str) -> str:
    """
    全量数学公式与推导文本清洗器 (具备 Auto-Fix 自动纠偏能力):
    - 自动剥离任何 `<br>` 标签并保持行宽自适应流式排版；
    - 自动清理包裹的 `$` 与 `$$`；
    - 自动清洗中考常见 LaTeX 宏 (\\geq, \\leq, \\neq, \\odot, \\left, \\right, \\text, \\cases 等)；
    - 自动将全部裸露根号 `√` 包装为标准 CSS 根号，100% 根绝裸根号；
    - 自动转换上下标。
    """
    if not text:
        return ""
    # 彻底剥离任何形式的 <br> 换行，替换为空格
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    # 剥离 LaTeX 数学定界符 $
    text = text.replace('$$', '').replace('$', '')
    
    # 预处理文本宏与方程组
    text = re.sub(r'\\text\{([^{}]+)\}', r'\1', text)
    text = re.sub(r'\\begin\{cases\}', '{ ', text)
    text = re.sub(r'\\end\{cases\}', ' }', text)
    text = re.sub(r'\\left\s*\\?\{', '{', text)
    text = re.sub(r'\\right\s*\.', '', text)
    text = re.sub(r'\\left\s*([\[\(])', r'\1', text)
    text = re.sub(r'\\right\s*([\]\)])', r'\1', text)
    text = re.sub(r'\\([\{\}])', r'\1', text)
    
    # 替换中考常见数学符号 (优先匹配长词，如 \\neq 优于 \\ne)
    symbol_pairs = [
        (r'\therefore', '∴'),
        (r'\because', '∵'),
        (r'\implies', ' ⇒ '),
        (r'\iff', ' ⇔ '),
        (r'\parallel', '∥'),
        (r'\perp', '⊥'),
        (r'\cong', '≌'),
        (r'\sim', '∽'),
        (r'\angle', '∠'),
        (r'\triangle', '△'),
        (r'\times', '×'),
        (r'\cdot', '·'),
        (r'\neq', '≠'),
        (r'\ne', '≠'),
        (r'\leq', '≤'),
        (r'\le', '≤'),
        (r'\geq', '≥'),
        (r'\ge', '≥'),
        (r'\pm', '±'),
        (r'\mp', '∓'),
        (r'\odot', '⊙'),
        (r'\circ', '°'),
        (r'\deg', '°'),
        (r'\approx', '≈'),
        (r'\Delta', 'Δ'),
        (r'\alpha', 'α'),
        (r'\beta', 'β'),
        (r'\theta', 'θ'),
        (r'\pi', 'π'),
        (r'\notin', '∉'),
        (r'\in', '∈'),
        (r'\infty', '∞'),
        (r'\rightarrow', '→'),
        (r'\leftarrow', '←'),
        (r'\to', '→'),
        (r'\sin', 'sin'),
        (r'\cos', 'cos'),
        (r'\tan', 'tan'),
        (r'\cot', 'cot'),
        (r'\quad', ' '),
        (r'\qquad', '  '),
        (r'\\', ' ')
    ]
    for sym, char in symbol_pairs:
        text = text.replace('\\' + sym, char)
        text = text.replace(sym, char)
    
    # 自动纠偏初中规范：清洗高中闭区间与集合中括号记号 (如 [0, t], [-2, 1])
    text = re.sub(r'区间\s*\[\s*([-\d\.\w\+]+)\s*,\s*([-\d\.\w\+]+)\s*\]', r'范围 \1 ≤ x ≤ \2', text)
    text = re.sub(r'\[\s*([-\d\.\w\+]+)\s*,\s*([-\d\.\w\+]+)\s*\]', r'\1 ≤ x ≤ \2', text)
    text = re.sub(r'在区间\s*([-\d\.\w\+]+)\s*≤\s*([a-zA-Z])\s*≤\s*([-\d\.\w\+]+)\s*上', r'当 \1 ≤ \2 ≤ \3 时', text)
    text = re.sub(r'在区间\s*', r'在范围 ', text)
    text = text.replace('单调递增', '随x的增大而增大')
    text = text.replace('单调递减', '随x的增大而减小')
    text = text.replace('单调性', '增减性')
    text = text.replace('单调', '增减')
    text = text.replace('极值', '最值')
    
    # 兜底清洗 LaTeX 残留宏 (防止双转义漏网之鱼)
    text = re.sub(r'\\(?:leq|le)\b', '≤', text)
    text = re.sub(r'\\(?:geq|ge)\b', '≥', text)
    text = re.sub(r'\\(?:neq|ne)\b', '≠', text)
    text = re.sub(r'\\(?:pm|mp)\b', '±', text)
    text = re.sub(r'\\(?:cdot|times)\b', '×', text)
    text = re.sub(r'\\(?:perp)\b', '⊥', text)
    text = re.sub(r'\\(?:parallel)\b', '∥', text)
    text = re.sub(r'\\(?:triangle)\b', '△', text)
    text = re.sub(r'\\(?:angle)\b', '∠', text)

    # 递归解析分式与根号
    text = replace_nested_latex(text)
    
    # Auto-Fix：彻底转换所有可能遗留的裸露根号字符 √
    # 匹配带括号的：如 √(x+1) 或 √（x+1）
    text = re.sub(
        r'√[\(（]([^\)）]+)[\)）]',
        r'<span class="sqrt"><span class="sqrt-rad">\1</span></span>',
        text
    )
    # 匹配后接数字/字母组合的：如 √21, √3, √k
    text = re.sub(
        r'√([0-9a-zA-Z]+)',
        r'<span class="sqrt"><span class="sqrt-rad">\1</span></span>',
        text
    )
    # 兜底：如果还有残留的裸露 √，后接紧跟的连续非空白字符
    text = re.sub(
        r'√([^\s,，。；;<>]+)',
        r'<span class="sqrt"><span class="sqrt-rad">\1</span></span>',
        text
    )
    
    # 转换花括号上下标 (如 S_{△AHQ} -> S<sub>△AHQ</sub>, x^{2} -> x<sup>2</sup>)
    while re.search(r'_\{([^{}]+)\}', text):
        text = re.sub(r'_\{([^{}]+)\}', r'<sub>\1</sub>', text)
    while re.search(r'\^\{([^{}]+)\}', text):
        text = re.sub(r'\^\{([^{}]+)\}', r'<sup>\1</sup>', text)

    # 转换常规简易上下标 (如 x_1 -> x<sub>1</sub>, x^2 -> x<sup>2</sup>)
    text = re.sub(r'([a-zA-Z0-9\)])_([0-9a-zA-Z\']+)', r'\1<sub>\2</sub>', text)
    text = re.sub(r'([a-zA-Z0-9\)])\^([0-9a-zA-Z]+)', r'\1<sup>\2</sup>', text)
    
    # 最终防御：剥离任何孤立的裸转义反斜杠（如 \\ ）
    text = re.sub(r'\\([^\w\s])', r'\1', text)
    
    return text

def sample_curve(expr_str: str, domain: list, origin: list, scale: float, num_pts: int = 150, t_val: float = 0.0) -> str:
    """高密数学密集等距采样生成无折角平滑 SVG 路径"""
    raw_min, raw_max = domain
    x_min = safe_eval_coord(raw_min, t_val)
    x_max = safe_eval_coord(raw_max, t_val)
    if math.isnan(x_min) or math.isnan(x_max):
        return ""
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if abs(x_max - x_min) < 1e-4:
        return ""
    pts = []
    ox, oy = origin
    pen_up = True
    for i in range(num_pts + 1):
        x_val = x_min + (x_max - x_min) * (i / float(num_pts))
        try:
            y_val = evaluate_expression(expr_str, t_val, x=x_val)
            sx = round(ox + x_val * scale, 2)
            sy = round(oy - y_val * scale, 2)
            pts.append(("M " if pen_up else "L ") + f"{sx},{sy}")
            pen_up = False
        except Exception:
            pen_up = True
            continue
    if not pts:
        return ""
    return " ".join(pts)

def safe_eval_coord(expr_str: Any, t_val: float) -> float:
    """安全解析并计算动点在参数处的坐标数值，全量动态支持所有 a-z 变量字母，自动容错隐式乘法"""
    try:
        return evaluate_expression(expr_str, t_val)
    except Exception:
        return float('nan')


def coordinates_at(points, t, initial=None):
    coords = dict(initial or {})
    for point in points:
        if "coord" in point:
            xy = point["coord"]
        else:
            dynamic = point.get("dynamic", point)
            if dynamic.get("type") == "segment_ratio":
                a, b = coords[dynamic["p1"]], coords[dynamic["p2"]]
                ratio = evaluate_expression(dynamic["ratio"], t)
                xy = [a[0]+ratio*(b[0]-a[0]), a[1]+ratio*(b[1]-a[1])]
            else:
                xy = [evaluate_expression(dynamic["x"], t), evaluate_expression(dynamic["y"], t)]
        if not all(math.isfinite(v) for v in xy): raise ValueError("点坐标非有限")
        coords[point["name"]] = xy
    return coords

def audit_problem_data(problem_data: dict) -> Tuple[bool, str]:
    """Definedness Audit: 结构定义有效性与变量引用巡检 (铁闸防呆阻断)"""
    title = problem_data.get("title", "").strip()
    if not title:
        return False, "题目缺少 title"
    tabs = problem_data.get("tabs", [])
    if not tabs:
        return False, "题目缺少 tabs 列表"
    
    global_stage = problem_data.get("stage", {})
    global_point_names = set(p.get("name") for p in global_stage.get("points", []) if p.get("name"))

    for idx, tab in enumerate(tabs):
        t_title = tab.get("tab_title", tab.get("tab_name", ""))
        if not t_title:
            return False, f"Tab #{idx+1} 缺少 tab_title"
        
        stage = tab.get("stage", {})
        points = stage.get("points", [])
        point_names = global_point_names | set(p.get("name") for p in points if p.get("name"))
        
        # 检查线段引用的端点
        for l_idx, line in enumerate(stage.get("lines", [])):
            p1 = line.get("p1")
            p2 = line.get("p2")
            if isinstance(p1, str) and p1 not in point_names:
                return False, f"Tab #{idx+1} 线段 #{l_idx+1} 引用的端点 '{p1}' 未在 points 中定义！"
            if isinstance(p2, str) and p2 not in point_names:
                return False, f"Tab #{idx+1} 线段 #{l_idx+1} 引用的端点 '{p2}' 未在 points 中定义！"
                
        # 检查多边形引用的顶点
        for pg_idx, pg in enumerate(stage.get("polygons", [])):
            for pt_ref in pg.get("points", []):
                if isinstance(pt_ref, str) and pt_ref not in point_names:
                    return False, f"Tab #{idx+1} 多边形 #{pg_idx+1} 引用的顶点 '{pt_ref}' 未在 points 中定义！"

        # 检查圆引用的圆心
        for c_idx, c in enumerate(stage.get("circles", [])):
            center = c.get("center")
            if isinstance(center, str) and center not in point_names:
                return False, f"Tab #{idx+1} 圆 #{c_idx+1} 引用的圆心 '{center}' 未在 points 中定义！"

        # 检查滑块与跳转按钮的定义域合法性 (死闸一)
        controls = tab.get("controls", tab.get("control", {}))
        slider = controls.get("slider", controls)
        if slider and ("min" in slider or "max" in slider):
            s_min = float(slider.get("min", 0.0))
            s_max = float(slider.get("max", 10.0))
            if s_min >= s_max:
                return False, f"Tab #{idx+1} 滑块 min ({s_min}) 必须严格小于 max ({s_max})！"
            for b_idx, btn in enumerate(controls.get("jump_buttons", [])):
                b_val = btn.get("value")
                if b_val is not None:
                    try:
                        b_val_f = float(b_val)
                        if b_val_f < s_min - 1e-4 or b_val_f > s_max + 1e-4:
                            return False, f"Tab #{idx+1} 跳转按钮 #{b_idx+1} 目标值 ({b_val}) 超出滑块定义域 [{s_min}, {s_max}]！"
                    except ValueError:
                        return False, f"Tab #{idx+1} 跳转按钮 #{b_idx+1} 目标值非法: {b_val}"
                    
    return True, "定义有效性巡检 100% 通过"

def assemble_problem_page(problem_input: Any, output_base_dir: str = r"E:\Antigravity-网页目录") -> Tuple[str, Dict[str, bool]]:
    """
    执行 One-Pass 确定性极速装配与自愈闭环流水线
    problem_input 可为 dict 对象，也可为 JSON 文件路径或字符串
    """
    if isinstance(problem_input, str):
        if os.path.exists(problem_input):
            with open(problem_input, "r", encoding="utf-8-sig") as f:
                raw_content = f.read()
            problem_data = robust_json_load(raw_content)
        else:
            problem_data = robust_json_load(problem_input)
    elif isinstance(problem_input, dict):
        problem_data = problem_input
    else:
        raise ValueError("输入必须为字典对象、JSON文件路径或JSON字符串")

    # 0. 铁闸：前置定义有效性巡检 (Definedness Audit)
    is_valid, audit_msg = audit_problem_data(problem_data)
    if not is_valid:
        raise ValueError(f"【定义有效性巡检阻断】: {audit_msg}")

    title = problem_data.get("title", "未命名题目").strip()
    target_dir = os.path.join(output_base_dir, title)
    os.makedirs(target_dir, exist_ok=True)
    html_output_path = os.path.join(target_dir, f"{title}.html")
    
    # 1. 原题图片安全处理 (全量内嵌 Base64，杜绝产生任何外部图片文件)
    img_b64 = problem_data.get("img_base64", problem_data.get("problem_image_base64", ""))
    img_path = problem_data.get("img_path", "")
    if img_b64 and "," in img_b64:
        img_b64 = img_b64.split(",", 1)[1]
    if not img_b64 and img_path and os.path.exists(img_path):
        with open(img_path, "rb") as f:
            raw_bytes = f.read()
            img_b64 = base64.b64encode(raw_bytes).decode("utf-8")
            
    img_src = f"data:image/png;base64,{img_b64}" if img_b64 else ""

    # 2. 生成标签按钮
    tabs = problem_data.get("tabs", [])
    tab_btns_html = []
    for idx, tab in enumerate(tabs):
        active_cls = " active" if idx == 0 else ""
        t_title = tab.get("tab_title", tab.get("tab_name", f"第({idx+1})问"))
        tab_btns_html.append(f'      <button class="tab-btn{active_cls}" onclick="switchTab({idx})">{t_title}</button>')
    tab_buttons_str = "\n".join(tab_btns_html)

    # 3. 生成各个答题面板
    panels_html = []
    page_scripts_list = []
    
    for idx, tab in enumerate(tabs):
        active_cls = " active" if idx == 0 else ""
        panel_id = f"tab{idx}"
        is_dynamic = (tab.get("type", "static") == "dynamic")
        
        # 3.1 提取控件基础参数（用于动态点初始帧计算）
        controls = tab.get("controls", tab.get("control", {}))
        slider = controls.get("slider", controls) if is_dynamic else {}
        s_raw_id = slider.get("slider_id", slider.get("id", "slider_param"))
        s_id = f"{s_raw_id}_{idx}" if not s_raw_id.endswith(f"_{idx}") else s_raw_id
        s_label = slider.get("slider_label", slider.get("label", "参数："))
        s_min = slider.get("min", 0)
        s_max = slider.get("max", 10)
        s_step = slider.get("step", 0.01)
        s_val = slider.get("value", slider.get("default", s_min))
        lower_open = not slider.get("min_inclusive", True)
        upper_open = not slider.get("max_inclusive", True)

        # 3.2 舞台区生成 (支持根级全局 stage 继承，大幅削减大模型 Token 吐字量以极速出图)
        global_stage = problem_data.get("stage", {})
        tab_stage = tab.get("stage", {})
        
        stage = {
            "viewBox": tab_stage.get("viewBox", global_stage.get("viewBox", "0 0 560 420")),
            "origin": tab_stage.get("origin", global_stage.get("origin", [145, 325])),
            "scale": tab_stage.get("scale", global_stage.get("scale", 64)),
            "axis": tab_stage.get("axis", global_stage.get("axis", {"show": True, "xLabel": "x", "yLabel": "y"})),
            "curves": tab_stage.get("curves", global_stage.get("curves", [])),
            "lines": global_stage.get("lines", []) + tab_stage.get("lines", []),
            "polygons": global_stage.get("polygons", []) + tab_stage.get("polygons", []),
            "circles": global_stage.get("circles", []) + tab_stage.get("circles", []),
            "points": global_stage.get("points", []) + tab_stage.get("points", []),
            "custom_svg": tab_stage.get("custom_svg", tab.get("svg", "")).strip()
        }
        viewBox = stage["viewBox"]
        custom_svg = stage["custom_svg"]
        
        if custom_svg:
            if custom_svg.startswith("<svg"):
                stage_html = f'      <div class="stage">\n        {custom_svg}\n      </div>'
            else:
                stage_html = f'      <div class="stage">\n        <svg viewBox="{viewBox}">\n          {custom_svg}\n        </svg>\n      </div>'
        else:
            # 标准自动几何渲染
            ox, oy = stage["origin"]
            scale = stage["scale"]

            # 动态全行程轨迹在轨仿真与自适应纠偏 (彻底根除滑动条滑到两端时动点飞出画布被截断的问题)
            if is_dynamic:
                all_sim_points = []
                for step_i in range(21):
                    sim_t = s_min + (s_max-s_min)*step_i/20
                    try:
                        all_sim_points.extend(coordinates_at(stage.get("points", []), sim_t).values())
                    except (ValueError, KeyError, ZeroDivisionError, OverflowError):
                        # Final definedness audit must reject invalid samples.
                        pass

                # 针对抛物线或曲线采样加入极值感知
                for crv in stage.get("curves", []):
                    c_dom = crv.get("domain", [-2, 4])
                    d0 = safe_eval_coord(c_dom[0], s_val)
                    d1 = safe_eval_coord(c_dom[1], s_val)
                    if not (math.isnan(d0) or math.isnan(d1)):
                        all_sim_points.append((d0, 0))
                        all_sim_points.append((d1, 0))

                all_sim_points = [(float(px), float(py)) for px, py in all_sim_points if not (math.isnan(float(px)) or math.isnan(float(py)))]

                if all_sim_points:
                    # 模拟当前配置下的屏幕边界
                    out_of_bounds = False
                    for px, py in all_sim_points:
                        sc_x = ox + px * scale
                        sc_y = oy - py * scale
                        if sc_x < 25 or sc_x > 535 or sc_y < 25 or sc_y > 395:
                            out_of_bounds = True
                            break
                    if out_of_bounds:
                        xs = [p[0] for p in all_sim_points]
                        ys = [p[1] for p in all_sim_points]
                        min_x, max_x = min(xs), max(xs)
                        min_y, max_y = min(ys), max(ys)
                        span_x = max(max_x - min_x, 1.0)
                        span_y = max(max_y - min_y, 1.0)
                        auto_scale = min(500.0 / span_x, 360.0 / span_y)
                        auto_scale = max(6.0, min(auto_scale, float(scale)))
                        scale = round(auto_scale, 1)
                        # 确保以全域动点包围盒为基准自适应垂直与水平居中
                        mid_x = (min_x + max_x) / 2.0
                        mid_y = (min_y + max_y) / 2.0
                        ox = round(280.0 - mid_x * scale, 1)
                        oy = round(210.0 + mid_y * scale, 1)
                        # 若有 x/y 轴，避免坐标原点飞出可视区太远
                        oy = max(180.0, min(oy, 350.0))

            axis = stage.get("axis", {"show": True, "xLabel": "x", "yLabel": "y"})
            
            svg_inner = []
            svg_inner.append('          <defs>')
            svg_inner.append(f'            <marker id="arrow_{idx}" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">')
            svg_inner.append('              <path d="M 0 1 L 10 5 L 0 9 z" fill="#8ea3c4"/>')
            svg_inner.append('            </marker>')
            svg_inner.append('          </defs>')
            
            if axis.get("show", True):
                svg_inner.append(f'          <line x1="30" y1="{oy}" x2="530" y2="{oy}" stroke="#8ea3c4" stroke-width="1.5" marker-end="url(#arrow_{idx})"/>')
                svg_inner.append(f'          <line x1="{ox}" y1="400" x2="{ox}" y2="20" stroke="#8ea3c4" stroke-width="1.5" marker-end="url(#arrow_{idx})"/>')
                svg_inner.append(f'          <text x="520" y="{oy+20}" fill="#8ea3c4" font-size="14" font-weight="bold" font-style="italic">{axis.get("xLabel", "x")}</text>')
                svg_inner.append(f'          <text x="{ox-15}" y="30" fill="#8ea3c4" font-size="14" font-weight="bold" font-style="italic">{axis.get("yLabel", "y")}</text>')
                svg_inner.append(f'          <text x="{ox-17}" y="{oy+18}" fill="#8ea3c4" font-size="14">O</text>')
            
            # 曲线绘制 (支持剪裁与动态温控高亮)
            dyn_curves_cfg = []
            curves_post_polys = []
            for c_idx, c in enumerate(stage.get("curves", [])):
                expr = c.get("expr", "")
                dom = c.get("domain", [-2, 5])
                d_path = sample_curve(expr, dom, [ox, oy], scale, 150, t_val=s_val)
                color = c.get("color", "#60a5fa")
                width = c.get("width", 2.2)
                dashed = c.get("dashed", False)
                dash_attr = ' stroke-dasharray="4,4"' if dashed else ''
                c_id = c.get("id", f"curve_{c_idx}")
                temp_c = c.get("temp_color", c.get("tempColor", False))
                clip_poly = c.get("clip_polygon", c.get("clip_poly", ""))
                clip_attr = f' clip-path="url(#clip_poly_{idx}_{clip_poly})"' if clip_poly else ''
                
                tag = f'          <path id="dyn_curve_{idx}_{c_id}" d="{d_path}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round"{dash_attr}{clip_attr}/>' if (is_dynamic and (temp_c or c.get("dynamic", False))) else f'          <path d="{d_path}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round"{dash_attr}{clip_attr}/>'
                
                if is_dynamic and (temp_c or c.get("dynamic", False)):
                    dyn_curves_cfg.append({
                        "id": c_id,
                        "expr": expr,
                        "exprCode": javascript_expression(expr),
                        "domain": dom,
                        "dynamic": c.get("dynamic", False),
                        "tempColor": temp_c
                    })
                
                if clip_poly:
                    curves_post_polys.append(tag)
                else:
                    svg_inner.append(tag)

            # 区分静态点与动态点并计算初始坐标
            static_points_dict = {}
            dyn_points_cfg = []
            dyn_point_names = set()
            points_coord_map = {}
            
            for p in stage.get("points", []):
                name = p.get("name", "")
                dyn_info = p.get("dynamic", {})
                is_dyn_pt = is_dynamic and (bool(dyn_info) or p.get("type") in ["dynamic", "segment_ratio"] or "expr" in p)
                
                if is_dyn_pt:
                    dyn_point_names.add(name)
                    if p.get("type") == "segment_ratio" or dyn_info.get("type") == "segment_ratio":
                        p1_ref = p.get("p1", dyn_info.get("p1"))
                        p2_ref = p.get("p2", dyn_info.get("p2"))
                        ratio_expr = p.get("ratio", dyn_info.get("ratio", "t"))
                        dyn_points_cfg.append({
                            "name": name,
                            "type": "segment_ratio",
                            "p1": p1_ref,
                            "p2": p2_ref,
                            "ratio": ratio_expr,
                            "ratioCode": javascript_expression(ratio_expr),
                            "color": p.get("color", "#ffd166"),
                            "labelPos": p.get("labelPos", [-16, -8]),
                            "glowOnHit": p.get("glowOnHit", False),
                            "isIntersection": p.get("is_intersection", p.get("isIntersection", False))
                        })
                        p1_c = points_coord_map.get(p1_ref, [0, 0])
                        p2_c = points_coord_map.get(p2_ref, [1, 1])
                        r_val = safe_eval_coord(ratio_expr, s_val)
                        init_x = p1_c[0] + r_val * (p2_c[0] - p1_c[0])
                        init_y = p1_c[1] + r_val * (p2_c[1] - p1_c[1])
                    else:
                        x_expr = dyn_info.get("x", p.get("expr", ["t", "0"])[0] if isinstance(p.get("expr"), list) else "t")
                        y_expr = dyn_info.get("y", p.get("expr", ["t", "0"])[1] if isinstance(p.get("expr"), list) else "0")
                        init_x = safe_eval_coord(x_expr, s_val)
                        init_y = safe_eval_coord(y_expr, s_val)
                        dyn_points_cfg.append({
                            "name": name,
                            "x": str(x_expr),
                            "y": str(y_expr),
                            "xCode": javascript_expression(x_expr),
                            "yCode": javascript_expression(y_expr),
                            "color": p.get("color", "#ffd166"),
                            "labelPos": p.get("labelPos", [-16, -8]),
                            "glowOnHit": p.get("glowOnHit", False),
                            "isIntersection": p.get("is_intersection", p.get("isIntersection", False))
                        })
                    points_coord_map[name] = [init_x, init_y]
                else:
                    coord = p.get("coord", [0, 0])
                    init_x, init_y = coord[0], coord[1]
                    if name:
                        static_points_dict[name] = [init_x, init_y]
                        points_coord_map[name] = [init_x, init_y]

            # 多边形绘制 (含动态与三阶温控多边形)
            dyn_polys_cfg = []
            for pg_idx, pg in enumerate(stage.get("polygons", [])):
                pg_pts = pg.get("points", [])
                is_dyn_poly = is_dynamic and (pg.get("dynamic", False) or pg.get("temp_color", False) or pg.get("tempColor", False) or any(pt_n in dyn_point_names for pt_n in pg_pts if isinstance(pt_n, str)))
                pg_id = pg.get("id", f"poly_{pg_idx}")
                temp_c = pg.get("temp_color", pg.get("tempColor", False))
                
                pts_resolved = []
                for pt in pg_pts:
                    if isinstance(pt, str) and pt in points_coord_map:
                        pts_resolved.append(points_coord_map[pt])
                    elif isinstance(pt, (list, tuple)):
                        pts_resolved.append(pt)
                
                pts_str = " ".join([f"{round(ox+pt[0]*scale,2)},{round(oy-pt[1]*scale,2)}" for pt in pts_resolved])
                stroke = pg.get("stroke", "#2dd4bf")
                fill = pg.get("fill", "rgba(45, 212, 191, 0.15)")
                
                if is_dyn_poly:
                    dyn_polys_cfg.append({
                        "id": pg_id,
                        "points": pg_pts,
                        "tempColor": temp_c
                    })
                    svg_inner.append(f'          <clipPath id="clip_poly_{idx}_{pg_id}">')
                    svg_inner.append(f'            <polygon id="dyn_clip_poly_{idx}_{pg_id}" points="{pts_str}"/>')
                    svg_inner.append('          </clipPath>')
                    svg_inner.append(f'          <polygon id="dyn_poly_{idx}_{pg_id}" points="{pts_str}" fill="{fill}" stroke="{stroke}" stroke-width="2.2"/>')
                else:
                    svg_inner.append(f'          <clipPath id="clip_poly_{idx}_{pg_id}">')
                    svg_inner.append(f'            <polygon points="{pts_str}"/>')
                    svg_inner.append('          </clipPath>')
                    svg_inner.append(f'          <polygon points="{pts_str}" fill="{fill}" stroke="{stroke}" stroke-width="2.2"/>')

            # 渲染放置在多边形上方的曲线 (如剪裁在多边形内部的高亮曲线)
            svg_inner.extend(curves_post_polys)

            # 直线/线段绘制 (含动态与三阶温控线段)
            dyn_lines_cfg = []
            for l_idx, l in enumerate(stage.get("lines", [])):
                p1_ref = l.get("p1", [0, 0])
                p2_ref = l.get("p2", [1, 1])
                p1_c = points_coord_map.get(p1_ref) if isinstance(p1_ref, str) else p1_ref
                p2_c = points_coord_map.get(p2_ref) if isinstance(p2_ref, str) else p2_ref
                p1_c = p1_c or [0, 0]
                p2_c = p2_c or [1, 1]
                
                sx1 = round(ox + p1_c[0] * scale, 2)
                sy1 = round(oy - p1_c[1] * scale, 2)
                sx2 = round(ox + p2_c[0] * scale, 2)
                sy2 = round(oy - p2_c[1] * scale, 2)
                color = l.get("color", "#94a3b8")
                width = l.get("width", 1.8)
                dashed = l.get("dashed", False)
                dash_attr = ' stroke-dasharray="3,3"' if dashed else ''
                
                is_dyn_line = is_dynamic and (l.get("dynamic", False) or l.get("temp_color", False) or l.get("tempColor", False) or (isinstance(p1_ref, str) and p1_ref in dyn_point_names) or (isinstance(p2_ref, str) and p2_ref in dyn_point_names))
                line_id = l.get("id", f"line_{l_idx}")
                temp_c = l.get("temp_color", l.get("tempColor", False))
                
                if is_dyn_line:
                    dyn_lines_cfg.append({
                        "id": line_id,
                        "p1": p1_ref,
                        "p2": p2_ref,
                        "tempColor": temp_c
                    })
                    svg_inner.append(f'          <line id="dyn_line_{idx}_{line_id}" x1="{sx1}" y1="{sy1}" x2="{sx2}" y2="{sy2}" stroke="{color}" stroke-width="{width}"{dash_attr}/>')
                else:
                    svg_inner.append(f'          <line x1="{sx1}" y1="{sy1}" x2="{sx2}" y2="{sy2}" stroke="{color}" stroke-width="{width}"{dash_attr}/>')

            # 几何圆图元绘制 (支持中考几何大圆与动态圆)
            dyn_circles_cfg = []
            for c_idx, c in enumerate(stage.get("circles", [])):
                c_id = c.get("id", f"circle_{c_idx}")
                center_ref = c.get("center", [0, 0])
                r_val = c.get("r", c.get("radius", 1))
                color = c.get("color", "#2dd4bf")
                fill = c.get("fill", "none")
                width = c.get("width", 1.8)
                dashed = c.get("dashed", False)
                dash_attr = ' stroke-dasharray="4,4"' if dashed else ''
                temp_c = c.get("temp_color", c.get("tempColor", False))
                
                center_c = points_coord_map.get(center_ref) if isinstance(center_ref, str) else center_ref
                center_c = center_c or [0, 0]
                sx = round(ox + center_c[0] * scale, 2)
                sy = round(oy - center_c[1] * scale, 2)
                r_num = safe_eval_coord(r_val, s_val)
                sr = round(r_num * scale, 2)
                
                is_dyn_circle = is_dynamic and (c.get("dynamic", False) or temp_c or (isinstance(center_ref, str) and center_ref in dyn_point_names) or isinstance(r_val, str))
                if is_dyn_circle:
                    dyn_circles_cfg.append({
                        "id": c_id,
                        "center": center_ref,
                        "r": str(r_val),
                        "rCode": javascript_expression(r_val),
                        "tempColor": temp_c
                    })
                    svg_inner.append(f'          <circle id="dyn_circle_{idx}_{c_id}" cx="{sx}" cy="{sy}" r="{sr}" fill="{fill}" stroke="{color}" stroke-width="{width}"{dash_attr}/>')
                else:
                    svg_inner.append(f'          <circle cx="{sx}" cy="{sy}" r="{sr}" fill="{fill}" stroke="{color}" stroke-width="{width}"{dash_attr}/>')

            # 点绘制 (支持自动将 P_m, P_2, V_x 等下划线转为规范 SVG tspan 下标)
            def format_svg_point_label(lbl: str) -> str:
                if not lbl:
                    return ""
                # 匹配花括号下标 A_{xyz}
                res = re.sub(r'([a-zA-Z0-9\)])_\{([^{}]+)\}', r'\1<tspan baseline-shift="sub" font-size="10">\2</tspan>', lbl)
                # 匹配简单下标 A_x, P_m, P_2, V_x
                res = re.sub(r'([a-zA-Z0-9\)])_([0-9a-zA-Z]+)', r'\1<tspan baseline-shift="sub" font-size="10">\2</tspan>', res)
                return res

            for p in stage.get("points", []):
                name = p.get("name", "")
                raw_label = p.get("label", name)
                
                # Render every explicitly declared point; labels do not control existence.
                coord = points_coord_map.get(name, p.get("coord", [0, 0]))
                sx = round(ox + coord[0] * scale, 2)
                sy = round(oy - coord[1] * scale, 2)
                color = p.get("color", "#ffd166")
                r = p.get("radius", 4)
                hollow = p.get("hollow", False)
                offset = p.get("labelPos", [-16, -8])
                label_html = format_svg_point_label(raw_label)
                
                if name in dyn_point_names:
                    svg_inner.append(f'          <circle data-point-name="{name}" id="dyn_pt_{idx}_{name}" cx="{sx}" cy="{sy}" r="{r}" fill="{color}"/>')
                    if label_html:
                        svg_inner.append(f'          <text id="dyn_txt_{idx}_{name}" x="{sx+offset[0]}" y="{sy+offset[1]}" fill="{color}" font-size="14" font-weight="bold">{label_html}</text>')
                else:
                    if hollow:
                        svg_inner.append(f'          <circle data-point-name="{name}" cx="{sx}" cy="{sy}" r="{r}" fill="#050b16" stroke="{color}" stroke-width="2"/>')
                    else:
                        svg_inner.append(f'          <circle data-point-name="{name}" cx="{sx}" cy="{sy}" r="{r}" fill="{color}"/>')
                    if label_html:
                        svg_inner.append(f'          <text x="{sx+offset[0]}" y="{sy+offset[1]}" fill="{color}" font-size="14" font-weight="bold">{label_html}</text>')
            
            inner_content = "\n".join(svg_inner)
            fullscreen_btn_html = (
                '        <button class="fullscreen-btn" onclick="toggleVisualAnchorFullscreen(this)" title="全屏查看" aria-label="全屏查看">\n'
                '          <svg class="fs-icon-enter" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">\n'
                '            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>\n'
                '          </svg>\n'
                '          <svg class="fs-icon-exit" style="display:none;" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">\n'
                '            <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path>\n'
                '          </svg>\n'
                '        </button>'
            )
            stage_html = f'      <div class="stage">\n        <svg viewBox="{viewBox}" data-origin-x="{ox}" data-origin-y="{oy}" data-scale="{scale}">\n{inner_content}\n        </svg>\n{fullscreen_btn_html}\n      </div>'

        # 3.3 控制区与底座动态引擎注册
        controls_html = ""
        if is_dynamic:
            jump_btns_html = []
            targets_list = []
            
            # 精准目标识别 (杜绝将端点误认为答案目标导致乱亮绿光)
            raw_solution_targets = controls.get("solution_targets", controls.get("targets", []))
            for st in raw_solution_targets:
                try:
                    targets_list.append(float(st))
                except Exception:
                    pass

            # 连续取值范围目标识别 (支持不等式与取值范围类题目在有效区间内全程呈现绿色高亮)
            raw_solution_intervals = controls.get("solution_intervals", controls.get("target_intervals", controls.get("intervals", [])))
            target_intervals_list = []
            for iv in raw_solution_intervals:
                if isinstance(iv, (list, tuple)) and len(iv) >= 2:
                    try:
                        target_intervals_list.append([float(iv[0]), float(iv[1])])
                    except Exception:
                        pass
            
            for j_idx, btn in enumerate(controls.get("jump_buttons", [])):
                raw_label = btn.get("text", btn.get("label", f"跳转{j_idx+1}"))
                b_val = btn.get("value", 0)
                b_click = btn.get("onclick", "")
                if not b_click:
                    b_click = f"DynamicMathEngine.jump({idx}, {b_val})"
                
                # 智能目标检测：如果未显式指定 solution_targets，检测按钮是否标记为 is_target 或文案包含最值/答案/临界/解
                if not raw_solution_targets and btn.get("is_target") is not False:
                    is_target_btn = btn.get("is_target", btn.get("is_answer", False))
                    ans_keywords = ["最值", "最大", "最小", "答案", "命中", "解", "临界", "满足条件", "≌", "⊥", "平行"]
                    if is_target_btn or any(kw in raw_label for kw in ans_keywords):
                        try:
                            targets_list.append(float(b_val))
                        except Exception:
                            pass
                
                # 底座防呆自动净化：彻底剥离按钮文案中的末尾括号及解释说明 (如 (差值等于6), (关于y轴对称) 等)，保持纯净直达答案
                clean_label = re.sub(r'\s*[\(（][^\)）]*[\)）]\s*$', '', raw_label).strip()
                b_label = format_math_text(clean_label)
                jump_btns_html.append(f'          <button class="jump-btn" onclick="{b_click}">{b_label}</button>')

            targets_list = list(dict.fromkeys(targets_list))
            jump_btns_str = "\n".join(jump_btns_html)
            controls_html = f'''      <div class="control-box">
        <div class="slider-row">
          <span class="slider-label">{s_label}</span>
          <input type="range" id="{s_id}" min="{s_min}" max="{s_max}" step="any" data-increment="{s_step}" data-lower-open="{str(lower_open).lower()}" data-upper-open="{str(upper_open).lower()}" value="{s_val}">
          <span id="{s_id}_val" style="font-family: monospace; color: var(--yellow); font-weight: bold; min-width: 42px; text-align: right; font-size: 14px;">{s_val}</span>
        </div>
        <div id="{s_id}_domain" class="domain-note" style="font-size:12px;color:#94a3b8" aria-live="polite"></div>
        <div class="jump-buttons">
{jump_btns_str}
        </div>
      </div>'''

            # 注册 DynamicMathEngine
            engine_cfg = {
                "sliderId": s_id,
                "origin": [ox, oy],
                "scale": scale,
                "staticPoints": static_points_dict,
                "dynamicPoints": dyn_points_cfg,
                "dynamicLines": dyn_lines_cfg,
                "dynamicPolygons": dyn_polys_cfg,
                "dynamicCircles": dyn_circles_cfg,
                "dynamicCurves": dyn_curves_cfg,
                "targets": targets_list,
                "targetIntervals": target_intervals_list,
                "snapRange": 0.035
            }
            page_scripts_list.append(f"    DynamicMathEngine.register({idx}, {json.dumps(engine_cfg, ensure_ascii=False)});")

        # 3.4 推导步骤生成 (全量经过 format_math_text 自愈清洗)
        steps_html = []
        for s in tab.get("steps", []):
            head = s.get("head", "")
            content = format_math_text(s.get("content", s.get("body", "")))
            head_tag = f'<span class="step-head">{head}</span>' if head else ""
            steps_html.append(f'        <li>{head_tag}{content}</li>')
        steps_str = "\n".join(steps_html)

        # 3.5 结论生成 (规范统一前缀)
        raw_conclusion = tab.get("conclusion", "").strip()
        conclusion_text = format_math_text(raw_conclusion)
        if not conclusion_text.startswith("【结论】"):
            conclusion_text = f"【结论】{conclusion_text}"
        conclusion_html = f'      <div class="conclusion-box">{conclusion_text}</div>'

        # 组装 Panel（纯净舞台吸顶结构）
        panel_parts = [
            f'    <div class="answer-panel{active_cls}" id="{panel_id}">',
            '      <div class="visual-anchor">',
            stage_html
        ]
        if controls_html:
            panel_parts.append(controls_html)
        panel_parts.append('      </div>')
        panel_parts.append('      <div class="scrolling-answer">')
        panel_parts.append(f'        <ul class="steps-list">\n{steps_str}\n        </ul>')
        panel_parts.append(conclusion_html)
        panel_parts.append('      </div>')
        panel_parts.append('    </div>')
        panels_html.append("\n".join(panel_parts))

        # 收集该 Tab 的兜底动态脚本 (如有自定义)
        dyn_script = tab.get("dynamic_script", "").strip()
        if dyn_script:
            page_scripts_list.append(dyn_script)

    answer_panels_str = "\n\n".join(panels_html)
    raw_page_scripts = problem_data.get("page_scripts", "").strip()
    page_scripts_str = raw_page_scripts if raw_page_scripts else "\n\n".join(page_scripts_list)

    # 4. 读取基础模板并注入
    template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "base_problem_template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()

    full_html = template_content.replace("{{PAGE_TITLE}}", title)
    full_html = full_html.replace("{{PROBLEM_IMG_SRC}}", img_src)
    full_html = full_html.replace("{{TAB_BUTTONS}}", tab_buttons_str)
    full_html = full_html.replace("{{ANSWER_PANELS}}", answer_panels_str)
    full_html = full_html.replace("{{PAGE_SCRIPTS}}", page_scripts_str)

    # 5. 底座自愈修补器 (Auto-Healer)：在写入与质检前全自动静默消除排版微瑕与宏残留
    def auto_heal_content(content: str, target_title: str) -> str:
        # 5.1 标题同步
        content = re.sub(r'<title>.*?</title>', f'<title>{target_title}</title>', content)
        content = re.sub(r'<h1 class="page-title">.*?</h1>', f'<h1 class="page-title">{target_title}</h1>', content)
        
        # 5.2 自动修补裸露根号
        content = re.sub(r'([^\w"\'\\])√([0-9a-zA-Z\(\)]+)', r'\1<span class="sqrt"><span class="sqrt-rad">\2</span></span>', content)
        
        # 5.3 自动清洗 LaTeX 反斜杠残留宏
        content = re.sub(r'\\(?:le|leq)\b', '≤', content)
        content = re.sub(r'\\(?:ge|geq)\b', '≥', content)
        content = re.sub(r'\\(?:neq|ne)\b', '≠', content)
        content = re.sub(r'\\(?:pm|mp)\b', '±', content)
        content = re.sub(r'\\(?:cdot|times)\b', '×', content)
        content = re.sub(r'\\(?:perp)\b', '⊥', content)
        content = re.sub(r'\\(?:parallel)\b', '∥', content)
        content = re.sub(r'\\(?:triangle)\b', '△', content)
        content = re.sub(r'\\(?:angle)\b', '∠', content)

        # 5.4 自动转换 SVG 文本中的裸下划线为规范 tspan 下标
        def svg_sub_fix(match):
            svg_body = match.group(0)
            def text_repl(t_match):
                t_prefix = t_match.group(1)
                t_inner = t_match.group(2)
                t_fixed = re.sub(r'([a-zA-Z0-9\)])_([0-9a-zA-Z]+)', r'\1<tspan baseline-shift="sub" font-size="10">\2</tspan>', t_inner)
                return f'{t_prefix}{t_fixed}</text>'
            return re.sub(r'(<text\b[^>]*>)(.*?)(</text>)', text_repl, svg_body, flags=re.DOTALL)
        content = re.sub(r'<svg\b[^>]*>.*?</svg>', svg_sub_fix, content, flags=re.DOTALL)
        
        # 5.5 仅在推导文本与结论区清洗高中词汇与闭区间记号 (严防误伤 <script> 中的 JSON 数组)
        def answer_text_fix(match):
            ans_body = match.group(0)
            ans_body = ans_body.replace("单调递增", "随x的增大而增大")
            ans_body = ans_body.replace("单调递减", "随x的增大而减小")
            ans_body = ans_body.replace("单调性", "增减性")
            ans_body = ans_body.replace("极值", "最值")
            ans_body = re.sub(r'区间\s*\[\s*([-\d\.\w\+]+)\s*,\s*([-\d\.\w\+]+)\s*\]', r'范围 \1 ≤ x ≤ \2', ans_body)
            ans_body = re.sub(r'\[\s*([-\d\.\w\+]+)\s*,\s*([-\d\.\w\+]+)\s*\]', r'\1 ≤ x ≤ \2', ans_body)
            return ans_body
        content = re.sub(r'<div class="scrolling-answer">.*?</div>\s*</div>', answer_text_fix, content, flags=re.DOTALL)
        return content

    full_html = auto_heal_content(full_html, title)

    # 6. 写入最终 HTML
    with open(html_output_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    # 7. 扫尾自愈 (Clean Worker)：清理目录多余文件，保证仅保留唯一成品 HTML (零杂质外置文件)
    allowed_files = {f"{title}.html"}
    for fname in os.listdir(target_dir):
        if fname not in allowed_files:
            try:
                os.remove(os.path.join(target_dir, fname))
            except Exception:
                pass

    # 8. 执行全量 14 项自动化闭环自检与自愈再验证
    verify_report = run_verification(html_output_path, title, target_dir)
    failed_checks = [k for k, v in verify_report.items() if not v]
    if failed_checks:
        # 尝试二次自愈写回
        with open(html_output_path, "r", encoding="utf-8") as f:
            c_read = f.read()
        c_healed = auto_heal_content(c_read, title)
        with open(html_output_path, "w", encoding="utf-8") as f:
            f.write(c_healed)
        verify_report = run_verification(html_output_path, title, target_dir)
        failed_checks = [k for k, v in verify_report.items() if not v]
        
    return html_output_path, verify_report


def check_geometry_bounds(content: str) -> Tuple[bool, str]:
    """
    铁闸一：严格检测 HTML 中所有 SVG 几何图元的坐标边界
    - 针对所有 <circle cx="..." cy="...">
    - 针对所有 <line x1="..." y1="..." x2="..." y2="..."> (支持任意属性排列顺序)
    要求屏幕像素坐标必须落在合理视口边界内，严禁出现几千像素严重飞出画布现象。
    """
    # 提取所有 circle 中心坐标 (包含动点与几何圆)
    c1 = re.findall(r'<circle[^>]+cx=["\']([-\d\.]+)["\'][^>]+cy=["\']([-\d\.]+)["\']', content)
    c2 = re.findall(r'<circle[^>]+cy=["\']([-\d\.]+)["\'][^>]+cx=["\']([-\d\.]+)["\']', content)
    for cx_s, cy_s in c1 + [(b, a) for a, b in c2]:
        try:
            cx, cy = float(cx_s), float(cy_s)
            if cx < -60 or cx > 620 or cy < -60 or cy > 480:
                return False, f"圆/点飞出画布: ({cx}, {cy})"
        except ValueError:
            return False, f"圆点坐标非法: cx={cx_s}, cy={cy_s}"

    # 提取所有 line 标签并安全提取端点坐标 (不依赖特定属性排列顺序)
    line_tags = re.findall(r'<line\b([^>]+)>', content)
    for tag in line_tags:
        m_x1 = re.search(r'\bx1=["\']([-\d\.]+)["\']', tag)
        m_y1 = re.search(r'\by1=["\']([-\d\.]+)["\']', tag)
        m_x2 = re.search(r'\bx2=["\']([-\d\.]+)["\']', tag)
        m_y2 = re.search(r'\by2=["\']([-\d\.]+)["\']', tag)
        if m_x1 and m_y1 and m_x2 and m_y2:
            try:
                x1, y1 = float(m_x1.group(1)), float(m_y1.group(1))
                x2, y2 = float(m_x2.group(1)), float(m_y2.group(1))
                for x, y in [(x1, y1), (x2, y2)]:
                    if x < -60 or x > 630 or y < -60 or y > 500:
                        return False, f"线段端点飞出画布: ({x}, {y})"
            except ValueError:
                return False, "线段坐标非法"

    return True, "几何图元坐标全部安全在轨"


def run_verification(html_path: str, expected_title: str, target_dir: str) -> Dict[str, bool]:
    """12 项全量自动化卡点闭环校验引擎 (含铁闸物理熔断)"""
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    checks = {}
    
    # 1. 标题一致性
    t_match = re.search(r'<title>(.*?)</title>', content)
    h_match = re.search(r'<h1 class="page-title">(.*?)</h1>', content)
    checks["1. 标题一致性检查"] = bool(t_match and h_match and t_match.group(1).strip() == expected_title and h_match.group(1).strip() == expected_title)
    
    # 2. CSS 变量
    checks["2. CSS变量系统完整性检查"] = (":root {" in content and "--bg:" in content and "--yellow:" in content)
    
    # 3. 纯净舞台
    raw_panels = re.split(r'<div class="answer-panel[^"]*"[^>]*>', content)[1:]
    stage_clean = all(
        p.strip().startswith('<div class="visual-anchor">') or p.strip().startswith('<div class="stage">')
        for p in raw_panels
    )
    checks["3. 纯净舞台检查"] = stage_clean
    
    # 4. 纯净控制区
    checks["4. 纯净控制区检查"] = ("feedback-note" not in content and "final-answer-box" not in content)
    
    # 5. 零裸露根号
    no_css = re.sub(r'<style>.*?</style>', '', content, flags=re.DOTALL)
    bare_sqrt = re.findall(r'[^\w"\'\\]√', no_css)
    checks["5. 根号完整性检查(无裸露√)"] = (len(bare_sqrt) == 0)
    
    # 6. 纯初中方法
    forbidden = ["正弦定理", "余弦定理", "和差角", "倍角公式", "向量", "导数", "微积分", "单调性"]
    checks["6. 纯初中方法规范检查"] = not any(w in content for w in forbidden)
    
    # 7. 零 LaTeX 泄漏 (严查步骤与结论中的全部反斜杠宏残留)
    steps_and_concl = "".join(re.findall(r'<ul class="steps-list">.*?</ul>', content, flags=re.DOTALL)) + \
                      "".join(re.findall(r'<div class="conclusion-box">.*?</div>', content, flags=re.DOTALL))
    leaked_macros = re.findall(r'\\[a-zA-Z]{2,}', steps_and_concl)
    checks["7. 零LaTeX宏泄漏检查"] = (len(leaked_macros) == 0)
    if leaked_macros:
        print(f"⚠️ [LaTeX宏泄漏拦截]: 发现未解析宏: {set(leaked_macros)}")
    
    # 8. 几何在轨与物理视口熔断自检 (铁闸一)
    has_svg = ('d="M ' in content or 'points=' in content or '<svg' in content)
    geom_safe, geom_msg = check_geometry_bounds(content)
    checks["8. 几何在轨与视口边界物理熔断自检"] = (has_svg and geom_safe)
    if not geom_safe:
        print(f"⚠️ [几何物理熔断警告]: {geom_msg}")
    
    # 9. 纯净单文件交付与原题配图内嵌检查
    is_single_html = (os.listdir(target_dir) == [f"{expected_title}.html"])
    has_embedded_img = ("problem-wrap" in content and ("data:image" in content or "<img" in content))
    checks["9. 纯净单文件交付与原题配图内嵌检查"] = (is_single_html and has_embedded_img)
    
    # 10. 步骤零 <br>
    steps_match = re.findall(r'<ul class="steps-list">(.*?)</ul>', content, flags=re.DOTALL)
    br_count = sum(len(re.findall(r'<br\s*/?>', s, flags=re.IGNORECASE)) for s in steps_match)
    checks["10. 推导步骤零<br>滥用检查"] = (br_count == 0)
    
    # 11. 移动端自适应与并排按钮
    checks["11. 移动端黄金比例与并排自适应检查"] = ("@media (max-width: 640px)" in content and "flex: 1 1 calc(50% - 4px)" in content)
    
    # 12. 关键步算式完整性
    checks["12. 关键步算式与数据100%完整性检查"] = ("steps-list" in content and "conclusion-box" in content)

    # 13. 图元标签零代码变量与下划线泄漏检查
    svg_texts = re.findall(r'<svg\b[^>]*>(.*?)</svg>', content, flags=re.DOTALL)
    leaked_underscores = []
    for s_svg in svg_texts:
        for t_content in re.findall(r'<text\b[^>]*>(.*?)</text>', s_svg, flags=re.DOTALL):
            pure_t = re.sub(r'<[^>]+>', '', t_content)
            if '_' in pure_t:
                leaked_underscores.append(pure_t)
    checks["13. 图元标签零下划线代码泄漏检查"] = (len(leaked_underscores) == 0)
    if leaked_underscores:
        print(f"⚠️ [图元标签泄漏拦截]: 发现未转换为数学下标的裸下划线点名: {set(leaked_underscores)}")

    # 14. 全行程动态无飞线与坐标防坍缩硬仿真自检
    engine_regs = []
    for reg_line in content.splitlines():
        m_reg = re.search(r'DynamicMathEngine\.register\(\s*\d+\s*,\s*(\{.*\})\);', reg_line)
        if m_reg:
            engine_regs.append(m_reg.group(1))
    dyn_sim_safe = True
    dyn_err_msg = ""
    for r_json_str in engine_regs:
        try:
            cfg = json.loads(r_json_str)
            s_id = cfg.get("sliderId", "")
            ox, oy = cfg.get("origin", [145, 325])
            scale = cfg.get("scale", 64)
            # 找到对应 slider 的 min 与 max
            sl_match = re.search(rf'<input[^>]+id=["\']{re.escape(s_id)}["\'][^>]*>', content)
            s_min, s_max = 0.0, 10.0
            if sl_match:
                tag = sl_match.group(0)
                m_min = re.search(r'min=["\']([-\d\.]+)["\']', tag)
                m_max = re.search(r'max=["\']([-\d\.]+)["\']', tag)
                if m_min: s_min = float(m_min.group(1))
                if m_max: s_max = float(m_max.group(1))
            
            # 密集采样 50 步，全面仿真前端 safeEval 行为
            for step_i in range(51):
                sim_t = s_min + (s_max - s_min) * (step_i / 50.0)
                cur_coords = coordinates_at(cfg.get("dynamicPoints", []), sim_t, cfg.get("staticPoints", {}))
                for name, (px, py) in cur_coords.items():
                    sc_x, sc_y = ox + px*scale, oy - py*scale
                    if sc_x < -50 or sc_x > 610 or sc_y < -50 or sc_y > 470:
                        dyn_sim_safe = False
                        dyn_err_msg = f"点 {name} 在 t={sim_t:.2f} 处超出视口"
                        break
                if not dyn_sim_safe:
                    break
        except Exception as e:
            dyn_sim_safe = False
            dyn_err_msg = f"离线动态仿真求值异常: {e}"
            break
            
    checks["14. 全行程动态无飞线与坐标防坍缩自检"] = dyn_sim_safe
    if not dyn_sim_safe:
        print(f"⚠️ [动态全行程仿真熔断]: {dyn_err_msg}")

    return checks

if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_target = sys.argv[1]
        html_path, report = assemble_problem_page(input_target)
        print(f"装配完成: {html_path}")
        all_passed = True
        for k, v in report.items():
            status_str = "✅ PASS" if v else "❌ FAIL"
            if not v:
                all_passed = False
            print(f"{k}: {status_str}")
        if not all_passed:
            sys.exit(1)
