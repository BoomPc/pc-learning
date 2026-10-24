"""Exact substitution probes catch displayed function-value mistakes, not just final answers."""
import pytest
from math_agent.tool_math import algebra_batch
from math_agent.tools import dispatch


def evaluate(expression,values,variables=None):
    return {'op':'evaluate','variables':variables or list(values),'expression':expression,'substitutions':values}


def test_original_function_and_changed_variable_endpoints_remain_distinct():
    operations=[evaluate('-t^2/2-t+5/2',{'t':x}) for x in [4,5,6]]
    operations += [evaluate('3-u^2/2',{'u':x}) for x in [5,6]]
    rows=algebra_batch(operations)
    assert rows['ok']
    assert [r['exact'] for r in rows['results']]==['-19/2','-15','-43/2','-19/2','-15']
    assert all(not r['remaining_variables'] for r in rows['results'])


@pytest.mark.parametrize('expression',['(t-1)/(t-1)','1/(t-1)','(t-1)^(-1)','t/abs(t)'])
def test_evaluation_preserves_original_holes_even_after_cancellation(expression):
    point=0 if 'abs' in expression else 1
    result=algebra_batch([evaluate(expression,{'t':point})])
    assert not result['ok'] and '定义域' in result['results'][0]['error']


def test_partial_evaluation_keeps_unresolved_variables_and_domain():
    row=algebra_batch([evaluate('1/(x-y)',{'x':'sqrt(4)'},['x','y'])])['results'][0]
    assert row['ok'] and row['exact']=='-1/(y - 2)' and row['remaining_variables']==['y']
    assert row['input_domain_restrictions']==['x - y != 0'] and row['domain_restrictions']==['2 - y != 0']


@pytest.mark.parametrize('values',[{'z':2},{'x':'y'},{'x':"__import__('os').getcwd()"},{'x':'sqrt(-1)'},{}])
def test_evaluation_rejects_undeclared_symbol_code_or_nonreal_input(values):
    assert not algebra_batch([evaluate('x^2',values,['x'])])['ok']


def test_evaluate_is_exposed_and_runs_through_real_bounded_tool_subprocess():
    from math_agent.tools import DEFINITIONS
    from jsonschema import validate
    args={'operations':[evaluate('2*x+3/x',{'x':'sqrt(6)/2'})]}
    schema=next(t['function']['parameters'] for t in DEFINITIONS if t['function']['name']=='algebra_batch')
    validate(args,schema)
    result=dispatch('algebra_batch',args)
    assert result['ok'] and result['results'][0]['exact']=='2*sqrt(6)'


def test_review_retains_tools_after_eleven_prior_calls_with_explicit_room(settings):
    import json,httpx
    from dataclasses import replace
    from math_agent.provider import DeepSeek
    from math_agent.parallel_budget import ParallelBudget
    from math_agent.tools import DEFINITIONS
    budget=ParallelBudget(16,timeout_seconds=240)
    for _ in range(11):
        with budget.request('offline prior slot fixture') as lease:lease.record_not_sent('offline fixture')
    requests=[];audit=[]
    args={'operations':[evaluate('-t^2/2-t+5/2',{'t':5})]}
    def handler(request):
        sent=json.loads(request.content);requests.append(sent)
        assert sent.get('tool_choice')!='none' and any(t['name']=='algebra_batch' for t in sent['tools'])
        if len(requests)==1:
            output=[{'type':'function_call','call_id':'eval-claim','name':'algebra_batch','arguments':json.dumps(args)}]
        else:
            observation=json.loads(next(v['output'] for v in sent['input'] if v.get('type')=='function_call_output'))
            assert observation['results'][0]['exact']=='-15'
            output=[{'type':'message','content':[{'type':'output_text','text':'{"ok":false}'}]}]
        return httpx.Response(200,json={'status':'completed','output':output,'usage':{'input_tokens':10,'output_tokens':20}})
    provider=DeepSeek(replace(settings,compact_tools=True,review_responses=True,max_calls=16,effort='low'),
        lambda k,v:audit.append((k,v)),httpx.MockTransport(handler));provider.shared_budget=budget
    try:
        result=provider.generate('review',[{'role':'user','content':'离线验证复核可用计算工具'}],
            tools=[t for t in DEFINITIONS if t['function']['name']=='algebra_batch'],dispatch=dispatch,
            output_schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']})
        assert result=={'ok':False} and len(requests)==2 and budget.calls==13
        assert not any(k=='agent_finalize' for k,v in audit)
    finally:provider.close()


def test_explicit_substitution_keys_declare_bound_variables_without_guessing_parameters():
    row=algebra_batch([evaluate('a+b+c',{'b':-5},['a','c'])])['results'][0]
    assert row['ok'] and row['exact']=='a + c - 5' and row['remaining_variables']==['a','c']
    row=algebra_batch([evaluate('-t^2/2-t+5/2',{'t':4},[])])['results'][0]
    assert row['ok'] and row['exact']=='-19/2'
    assert not algebra_batch([evaluate('x+y',{'x':2},[])])['ok'] # y is neither declared nor bound
    assert not algebra_batch([evaluate('x^2',{'z':2},['x'])])['ok'] # unused misspelled binding


def test_safe_fraction_aliases_keep_exactness_and_original_holes():
    row=algebra_batch([evaluate('-Rational(1,2)*t^2-t+Rational(5,2)',{'t':5},[])])['results'][0]
    assert row['ok'] and row['exact']=='-15'
    for expr in ['frac(t-1,t-1)','1/frac(t-1,1)','frac(1,t-1)']:
        result=algebra_batch([evaluate(expr,{'t':1})]);assert not result['ok'] and '定义域' in result['results'][0]['error']
    for expr in ["Rational(__import__('os'),2)",'Rational(1,0)','Rational(x,2)']:
        assert not algebra_batch([evaluate(expr,{'x':1},['x'])])['ok']
