"""Exact checks for explicitly defined single-variable functions in prose.

This does NOT solve a problem or verify general proofs. It checks supported
numeric function equalities and adjacent explicitly equivalent range bounds.
Definitions/claims remain bound to their original question and paragraph.
Unsupported/ambiguous syntax is reported as unobserved, never guessed true.
"""
import re
from .tool_math import expression,algebra_batch

NAME=r'[A-Za-z][A-Za-z0-9_]{0,7}'
NUM=r'[+\-]?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?(?:/\d+(?:\.\d+)?)?'
CALL_TEXT=rf'{NAME}\(\s*{NUM}\s*\)'
CALL=re.compile(rf'(?P<name>{NAME})\(\s*(?P<arg>{NUM})\s*\)')
DECL=re.compile(rf'(?:设|记|令|定义)\s*(?:函数\s*)?(?P<name>{NAME})(?:\(\s*(?P<arg>[A-Za-z])\s*\))?\s*=\s*(?P<expr>[A-Za-z0-9_+\-*/^().\s]+)')
TERM=rf'(?:{CALL_TEXT}|{NUM})'
CHAIN=re.compile(rf'(?P<lo>{TERM})\s*(?P<a><=?)\s*(?P<center>{NAME}(?:\([A-Za-z]\))?)\s*(?P<b><=?)\s*(?P<hi>{TERM})')
EQ=re.compile(rf'(?<![A-Za-z0-9_+*/.\-])(?P<call>{CALL_TEXT})\s*=\s*(?P<value>{NUM})(?![A-Za-z0-9_./*+\-(])')
BUILTINS={'sqrt','root','abs','sin','cos','tan','frac','Rational','pi','PI','SQRT2','SQRT3'}
TOKEN=re.compile(r'\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?|[A-Za-z][A-Za-z0-9_]*|\*\*|[+\-*/().]')


def ascii_math(text):
    value=text.translate(str.maketrans({'＝':'=','＋':'+','－':'-','−':'-','×':'*','·':'*',
        '÷':'/','（':'(','）':')','，':',','；':';','＜':'<','＞':'>','≤':'<=','≥':'>=',
        '²':'**2','³':'**3','½':'(1/2)'})).replace('^','**')
    value=re.sub(r'√(\d+(?:\.\d+)?)',r'sqrt(\1)',value).replace('√(','sqrt(')
    return value


def formula(text):
    """Make only unambiguous implicit multiplication explicit, then use AST whitelist."""
    text=ascii_math(text).strip()
    if len(text)>128:raise ValueError('formula too long for literal check')
    tokens=TOKEN.findall(text)
    if ''.join(tokens)!=re.sub(r'\s+','',text) or len(tokens)>60:raise ValueError('unsupported math text')
    names={t for t in tokens if re.fullmatch(NAME,t) and t not in BUILTINS}
    if any(len(n)!=1 for n in names):raise ValueError('ambiguous multi-letter symbol')
    out=[]
    def atom(t):return bool(re.fullmatch(NAME,t) or re.fullmatch(r'\d.*',t) or t==')')
    def starts(t):return bool(re.fullmatch(NAME,t) or re.fullmatch(r'\d.*',t) or t=='(')
    for token in tokens:
        if out and atom(out[-1]) and starts(token) and not (out[-1] in BUILTINS and token=='('):out.append('*')
        out.append(token)
    import sympy as s
    value=''.join(out);symbols={n:s.Symbol(n,real=True) for n in names}
    expression(value,symbols)
    return value,names


def fields(solution):
    for i,step in enumerate(solution.steps):
        for name in ('premise','rule','conclusion'):yield f'proof.steps.{i}.{name}',getattr(step,name)
    for i,text in enumerate(solution.cases):yield f'proof.cases.{i}',text
    yield 'proof.domain_and_boundaries',solution.domain_and_boundaries
    yield 'proof.result',solution.result


def collect(solutions):
    report={'issues':[],'observations':[],'unobserved':[],
        'scope':'Explicit single-variable definitions, numeric calls and adjacent equivalent range bounds only; not general mathematical proof.'}
    for solution in solutions:
        paragraphs=[(path,ascii_math(text)) for path,text in fields(solution)]
        called={m['name'] for _,text in paragraphs for m in CALL.finditer(text)}-BUILTINS
        if not called:continue
        registry={};ambiguous=set()
        for path,text in paragraphs:
            for match in DECL.finditer(text):
                name=match['name']
                if name not in called:continue
                try:
                    expr,names=formula(match['expr']);param=match['arg'] or (next(iter(names)) if len(names)==1 else None)
                    if not param or names-{param}:raise ValueError('not a supported single-variable definition')
                    current={'name':name,'argument':param,'expression':expr,'definition_path':path,'definition_quote':match.group(0)}
                    if name in registry:
                        # No guessed shadowing/branch scope. Different definitions
                        # of one name remain an explicit unobserved obligation.
                        old=registry[name]
                        import sympy as s
                        x=s.Symbol('z',real=True)
                        a=expression(old['expression'],{old['argument']:x})
                        b=expression(expr,{param:x})
                        if s.simplify(a-b)!=0:ambiguous.add(name)
                    else:registry[name]=current
                except (ValueError,SyntaxError,TypeError) as exc:
                    report['unobserved'].append({'question_id':solution.question_id,'path':path,'name':name,'reason':str(exc)[:200]})
        for name in called-set(registry)|ambiguous:
            report['unobserved'].append({'question_id':solution.question_id,'name':name,'reason':'missing or ambiguous explicit function definition'})
        for name in ambiguous:registry.pop(name,None)
        def number(text):
            prepared,names=formula(text)
            if names:raise ValueError('not a numeric constant')
            return expression(prepared,{})
        def term(text):
            match=CALL.fullmatch(text.strip())
            if not match:return number(text)
            definition=registry.get(match['name'])
            if definition is None:raise ValueError('unbound function')
            argument=number(match['arg'])
            row=algebra_batch([{'op':'evaluate','expression':definition['expression'],
                'variables':[definition['argument']], 'substitutions':{definition['argument']:str(argument)}}])['results'][0]
            if not row['ok'] or row['remaining_variables']:raise ValueError(row.get('error','unresolved variables'))
            value=expression(row['exact'],{})
            report['observations'].append({'question_id':solution.question_id,**definition,
                'call':text,'argument_value':str(argument),'exact':str(value),'domain_restrictions':row['input_domain_restrictions']})
            return value
        def failure(path,quote,detail):
            issue={'stage':'math','question_id':solution.question_id,'path':path,
                'code':'literal_function_inconsistency','detail':detail,'original_quote':quote}
            if issue not in report['issues']:report['issues'].append(issue)
        for path,text in paragraphs:
            for match in EQ.finditer(text):
                try:
                    actual=term(match['call']);expected=number(match['value'])
                    import sympy as s
                    if s.simplify(actual-expected).is_zero is False:
                        failure(path,match.group(0),f'原句 {match.group(0)} 与本问已定义函数不符：按原函数实际代入得到 {match["call"]}={actual}，不是 {expected}。保留原函数变量；换元后须另定义新函数或改回原变量端点，不得删除核验。')
                except (ValueError,SyntaxError,TypeError) as exc:
                    report['unobserved'].append({'question_id':solution.question_id,'path':path,'quote':match.group(0),'reason':str(exc)[:200]})
            chains=list(CHAIN.finditer(text))
            for left,right in zip(chains,chains[1:]):
                if left['center']!=right['center'] or not re.fullmatch(r'\s*[,;]?\s*(?:即|也即|也就是|等价于)\s*',text[left.end():right.start()]):continue
                quote=text[left.start():right.end()]
                # This guard checks literal endpoint replacement only. Different
                # operators may be legitimate after restricting to integers, and
                # expressions surrounding a matched term require general proof.
                before=text[:left.start()].rstrip();after=text[right.end():].lstrip()
                if (left['a'],left['b'])!=(right['a'],right['b']) or (before and before[-1] in '+-*/(') or (after and (after[0] in '+-*/(' or after[0].isascii() and after[0].isalnum())):
                    report['unobserved'].append({'question_id':solution.question_id,'path':path,'quote':quote,'reason':'not a direct same-operator numeric endpoint replacement'})
                    continue
                try:
                    lv=[term(left['lo']),term(left['hi'])];rv=[term(right['lo']),term(right['hi'])]
                    import sympy as s
                    if any(s.simplify(a-b).is_zero is False for a,b in zip(lv,rv)):
                        quote=text[left.start():right.end()]
                        failure(path,quote,f'原句把 {left.group(0)} 等同于 {right.group(0)}，但按已定义函数代入，前一范围的边界是({lv[0]}, {lv[1]})，后一范围是({rv[0]}, {rv[1]})，并不等价。不能把换元后自变量的端点当作原函数参数；请明确新函数或使用原函数对应端点。')
                except (ValueError,SyntaxError,TypeError) as exc:
                    report['unobserved'].append({'question_id':solution.question_id,'path':path,'quote':text[left.start():right.end()],'reason':str(exc)[:200]})
    return report
