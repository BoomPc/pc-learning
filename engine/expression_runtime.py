"""One validated arithmetic grammar, Python evaluation and generated JS expressions.

Only trusted code generates JS from the AST. No raw model expression enters new Function.
"""
import ast
import math
import operator
import re

FUNCTIONS = {"abs": abs, "min": min, "max": max, "sqrt": math.sqrt,
             "sin": math.sin, "cos": math.cos, "tan": math.tan}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}


def normalized(value):
    text = str(value).strip().replace("^", "**")
    text = re.sub(r"(\d)\s*((?![eE][+-]?\d)[a-zA-Z]|\()", r"\1*\2", text)
    text = re.sub(r"(\))\s*([a-zA-Z0-9\(])", r"\1*\2", text)
    return text


def tree(value):
    text = normalized(value)
    if len(text) > 600: raise ValueError("数学表达式过长")
    node = ast.parse(text, mode="eval").body
    if len(list(ast.walk(node))) > 160: raise ValueError("数学表达式过于复杂")
    return node


def evaluate(value, parameter=0, *, x=None):
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float): return n.value
        if isinstance(n, ast.Name):
            if n.id == "pi": return math.pi
            if len(n.id) == 1 and "a" <= n.id <= "z": return x if n.id == "x" and x is not None else parameter
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -visit(n.operand) if isinstance(n.op, ast.USub) else visit(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in OPS: return OPS[type(n.op)](visit(n.left), visit(n.right))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCTIONS and not n.keywords:
            return FUNCTIONS[n.func.id](*(visit(a) for a in n.args))
        raise ValueError("不支持的数学表达式")
    result = float(visit(tree(value)))
    if not math.isfinite(result): raise ValueError("数学表达式非有限")
    return result


def javascript(value):
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float) and math.isfinite(n.value): return repr(n.value)
        if isinstance(n, ast.Name):
            if n.id == "pi": return "Math.PI"
            if len(n.id) == 1 and "a" <= n.id <= "z": return n.id
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return "(" + ("-" if isinstance(n.op, ast.USub) else "+") + visit(n.operand) + ")"
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = visit(n.left), visit(n.right)
            if isinstance(n.op, ast.Pow): return f"Math.pow({a},{b})"
            if isinstance(n.op, ast.Mod): return f"((({a}%{b})+{b})%{b})"
            symbol = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(n.op)]
            return f"({a}{symbol}{b})"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCTIONS and not n.keywords:
            return "Math." + n.func.id + "(" + ",".join(visit(a) for a in n.args) + ")"
        raise ValueError("不支持的数学表达式")
    return visit(tree(value))
