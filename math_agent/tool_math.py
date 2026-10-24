"""Bounded local mathematics and lexical RAG, shared by the MCP worker and tests.

Expressions are parsed with an AST whitelist, never sympify/parse_expr/eval.
Geometry uses the same normalization and construction engine as the final page.
"""
from __future__ import annotations

import ast
import collections
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent


def expression(text, symbols, domain=None,domain_objects=None,used_names=None):
    import sympy as s
    text = str(text).strip().replace('^', '**')
    if len(text) > 600:
        raise ValueError('表达式过长')
    tree = ast.parse(text, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 160:
        raise ValueError('表达式过于复杂')
    def divide(a,b):
        if b==0:raise ValueError('除数为零')
        if b.free_symbols:
            if domain is not None:domain.append(str(b)+' != 0')
            if domain_objects is not None:domain_objects.append(b)
        return a/b
    def rational(a,b):
        if not a.is_Rational or not b.is_Rational:raise ValueError('Rational仅接受有理数常量；符号分式请用frac或/')
        return divide(a,b)
    funcs = {'sqrt': s.sqrt, 'root': s.sqrt, 'abs': s.Abs, 'sin': s.sin,
             'cos': s.cos, 'tan': s.tan, 'frac': divide,'Rational':rational}
    constants = {'pi': s.pi, 'PI': s.pi, 'SQRT2': s.sqrt(2), 'SQRT3': s.sqrt(3)}
    def visit(n):
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            if len(str(n.value)) > 30 or not math.isfinite(n.value):
                raise ValueError('数字超出范围')
            return s.Rational(str(n.value))
        if isinstance(n, ast.Name):
            if n.id in symbols:
                if used_names is not None:used_names.add(n.id)
                return symbols[n.id]
            if n.id in constants:
                return constants[n.id]
            raise ValueError('未声明变量 ' + n.id)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = visit(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp):
            a, b = visit(n.left), visit(n.right)
            if isinstance(n.op, ast.Add): return a + b
            if isinstance(n.op, ast.Sub): return a - b
            if isinstance(n.op, ast.Mult): return a * b
            if isinstance(n.op, ast.Div):return divide(a,b)
            if isinstance(n.op, ast.Pow):
                if not b.is_number or abs(b) > 20: raise ValueError('幂指数须为绝对值不超过20的常数')
                if domain is not None and b < 0 and a.free_symbols:
                    domain.append(str(a) + ' != 0')
                if domain_objects is not None and b < 0 and a.free_symbols:domain_objects.append(a)
                return a ** b
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs and not n.keywords:
            if len(n.args) > 2: raise ValueError('函数参数过多')
            return funcs[n.func.id](*(visit(a) for a in n.args))
        raise ValueError('只允许数学表达式，不允许属性、下标或任意函数调用')
    result = visit(tree.body)
    if result.has(s.zoo, s.nan, s.oo, -s.oo):
        raise ValueError('表达式无定义或非有限')
    return result


def algebra_batch(operations):
    import sympy as s
    if not isinstance(operations, list) or not 1 <= len(operations) <= 12:
        raise ValueError('一次提交1至12个计算')
    rows = []
    for op in operations:
        try:
            mode = op.get('op', 'simplify')
            names = op.get('variables', op.get('var', []))
            if isinstance(names, str): names = [names]
            if not isinstance(names,list):raise ValueError('variables须为变量名数组')
            explicit_names=set(names)
            substitutions=op.get('substitutions')
            if mode=='evaluate' and isinstance(substitutions,dict):names=list(dict.fromkeys([*names,*substitutions]))
            if len(names) > 4 or any(not isinstance(n,str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9]{0,7}', n) for n in names):
                raise ValueError('变量名须为字母数字，最多4个')
            symbols = {n: s.Symbol(n, real=True) for n in names}
            domain = []
            if mode == 'solve':
                eqs = op.get('equations') or op.get('expression') or op.get('expr') or []
                if isinstance(eqs, str): eqs = [eqs]
                if not names or not 1 <= len(eqs) <= 6: raise ValueError('solve 需要 variables 和1至6条 equations')
                expressions = []
                for eq in eqs:
                    parts = str(eq).split('=')
                    if len(parts) > 2: raise ValueError('每条方程最多一个等号')
                    expressions.append(expression(parts[0], symbols, domain) - expression(parts[1] if len(parts) == 2 else '0', symbols, domain))
                if all(e == 0 for e in expressions):
                    rows.append({'ok': True, 'status': 'identity', 'solutions': None,
                                 'domain_restrictions': sorted(set(domain)),
                                 'note': '恒等式，不是无解；所有满足原式定义域的实数取值均成立。'})
                    continue
                roots = s.solve(expressions, list(symbols.values()), dict=True, check=True)
                solutions = [{str(k): str(v) for k, v in r.items()} for r in roots if all(v.is_real is not False for v in r.values())]
                rows.append({'ok': True, 'status': 'candidates' if solutions else 'no_solution',
                             'solutions': solutions, 'domain_restrictions': sorted(set(domain)),
                             'note': '实数域候选解；仍须按原题排除不合位置、范围及退化条件的解'})
            else:
                restrictions=[]
                used=set()
                e = expression(op.get('expression', op.get('expr', '')), symbols, domain,restrictions,used)
                if mode=='evaluate':
                    substitutions=op.get('substitutions')
                    if not isinstance(substitutions,dict) or not substitutions or not set(substitutions)<=set(symbols):
                        raise ValueError('evaluate须以substitutions指定已声明变量的精确常量代入值')
                    if set(substitutions)-explicit_names-used:raise ValueError('substitutions含未出现在表达式、也未声明的变量，可能代入变量名写错')
                    values={symbols[name]:expression(value,{}) for name,value in substitutions.items()}
                    if any(value.is_real is not True for value in values.values()):
                        raise ValueError('evaluate代入值须为有限实数常量')
                    remaining=[]
                    for restriction in restrictions:
                        value=s.simplify(restriction.subs(values,simultaneous=True))
                        if value.is_zero is True:raise ValueError('代入值违反原式分母不为零的定义域条件')
                        if value.is_zero is not False:remaining.append(str(value)+' != 0')
                    result=s.simplify(e.subs(values,simultaneous=True))
                    if result.has(s.zoo,s.nan,s.oo,-s.oo) or result.is_real is False:
                        raise ValueError('代入结果无定义、非有限或不在实数范围')
                    rows.append({'ok':True,'exact':str(result),'approx':str(s.N(result,12)) if not result.free_symbols else None,
                        'substitutions':{name:str(values[symbols[name]]) for name in substitutions},
                        'remaining_variables':sorted(str(v) for v in result.free_symbols),
                        'input_domain_restrictions':sorted(set(domain)), 'domain_restrictions':sorted(set(remaining))})
                    continue
                if mode == 'simplify': e = s.simplify(e)
                elif mode == 'factor': e = s.factor(e)
                elif mode == 'expand': e = s.expand(e)
                else: raise ValueError('op 只支持 simplify、factor、expand、solve、evaluate')
                rows.append({'ok': True, 'exact': str(e), 'approx': str(s.N(e, 12)) if not e.free_symbols else None,
                             'domain_restrictions': sorted(set(domain))})
        except Exception as exc:
            rows.append({'ok': False, 'error': str(exc)[:400]})
    return {'ok': all(r['ok'] for r in rows), 'results': rows}


def tokens(text):
    text = str(text).lower()
    out = re.findall(r'[a-z0-9_]+', text)
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        out += [run[i:i+2] for i in range(len(run)-1)] or [run]
    return out


def knowledge_search(query, max_results=4):
    if not str(query).strip() or len(str(query)) > 2000:
        raise ValueError('请输入简短的题目条件和待求结论，最多2000字')
    cards = json.loads((HERE / 'math_knowledge.json').read_text())['cards']
    fields = ['title', 'keywords', 'conditions', 'method', 'pitfalls', 'construction']
    corpus = [tokens(' '.join(str(c.get(k, '')) for k in fields)) for c in cards]
    df = collections.Counter(t for doc in corpus for t in set(doc))
    avg = sum(map(len, corpus)) / len(corpus)
    qt = set(tokens(query))
    ranked = []
    for card, doc in zip(cards, corpus):
        tf = collections.Counter(doc)
        score = sum(math.log(1 + (len(cards)-df[t]+.5)/(df[t]+.5)) * tf[t]*2.2 / (tf[t]+1.2*(.25+.75*len(doc)/avg)) for t in qt if tf[t])
        if score > 0: ranked.append((score, card))
    ranked.sort(key=lambda row: (-row[0], row[1]['id']))
    if ranked:
        ranked = [row for row in ranked if row[0] >= ranked[0][0] * .3]
    return {'method': 'local BM25 with Chinese bigrams', 'corpus_version': '2026-10-10-v1',
            'matches': [dict(c, score=round(score, 3)) for score, c in ranked[:max(1, min(int(max_results), 5))]],
            'note': '检索条目是方法参考，不是本题答案；使用前核对全部适用条件，不匹配时不要套用。'}

