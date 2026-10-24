import copy
import json
import threading
import time
from dataclasses import replace
import httpx
import pytest
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import Runner,canonical_page
from math_agent.parallel_review import merge_parts,check_rounds
from math_agent.provider import DeepSeek
from math_agent.storage import write_json
from test_pipeline import MemoryCache,renderer
from test_review_passages import flat_review


def part(source,qid,verdict='pass',issue=None,condition_ids=None):
    return {'verdict':'revise' if issue else 'needs_input' if verdict=='unknown' else 'pass',
        'conditions':{c['id']:{'verdict':'pass','evidence':'逐项核对原条件'} for c in source['conditions'] if condition_ids is None or c['id'] in condition_ids},
        'questions':{qid:{'verdict':verdict,'evidence':'独立核对全部证明与边界'}},
        'issues':[issue] if issue else []}


def setup_review(settings,job,sample,*,bad=None,tools=False,incremental=False):
    if incremental:
        sample=copy.deepcopy(sample)
        for solution in sample[1]['solutions']:
            for step in solution['steps']:step['basis_ids']=['C1']
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    canonical_page(candidate,source)
    state={'peak':0,'active':0,'contexts':{},'calls':[],'histories':{},'bootstrap':[],'repairs':0,'screenshots':{}}
    lock=threading.Lock();barrier=threading.Barrier(2)
    def handler(request):
        body=json.loads(request.content)
        native='input' in body
        from math_agent.responses_transport import input_items
        history=body['input'] if native else input_items(body['messages'])
        text=next(p['text'] for m in history if m.get('role')=='user' and m.get('type')=='message'
                  for p in m['content'] if p.get('type')=='input_text' and p['text'].startswith('{"task":'))
        context=json.loads(text)['context']
        if 'parallel_review_scope' not in context:
            if 'previous' in context:
                state['repairs']+=1;state['bootstrap'].append('math_repair')
                proof=copy.deepcopy(sample[1]['solutions'][1]);proof.pop('question_id')
                proof['domain_and_boundaries']='0≤t≤2，两个端点面积均为0，单独核对成立'
                value={'updates':{'Q2':{'reason':'已重新代入原表达式核对两个端点，纠正对应取等条件的解释','proof':proof}}}
            elif 'source' in context:
                from math_agent.compact_output import pack
                state['bootstrap'].append('solve');value=pack(candidate)
            else:state['bootstrap'].append('source');value=source.model_dump()
            if native:
                return httpx.Response(200,json={'status':'completed','output':[{'type':'message','role':'assistant',
                    'content':[{'type':'output_text','text':json.dumps(value,ensure_ascii=False)}]}],
                    'usage':{'input_tokens':10,'output_tokens':20}})
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant',
                'content':json.dumps(value,ensure_ascii=False)}}],'usage':{'prompt_tokens':10,'completion_tokens':20}})
        qid=context['parallel_review_scope']['question_ids'][0]
        state['screenshots'][qid]=[p['text'] for m in history if isinstance(m.get('content'),list)
            for p in m['content'] if p.get('type')=='input_text' and p['text'].startswith('实际JSXGraph截图：')]
        assert [q['id'] for q in context['source']['questions']]==['Q1','Q2']
        assert [s['question_id'] for s in context['candidate']['solutions']]==['Q1','Q2']
        assert context['parallel_review_scope']['original_tabs']=={'Q1':0,'Q2':1}
        assert context['inspection_point_index']['0']['question_id']=='Q1'
        assert all(isinstance(p,str) for p in context['inspection_point_index']['0']['point_ids'])
        required=body['text']['format']['schema']['properties']['records']['required']
        assert set(required)==set(context['parallel_review_scope']['condition_ids']+[qid]+[p['id'] for p in context['literal_passages']])
        assert body['text']['format']['strict'] is True
        replies=[m for m in history if m.get('type')=='function_call_output']
        with lock:
            state['active']+=1;state['peak']=max(state['peak'],state['active'])
            state['contexts'][qid]=context;state['calls'].append(qid);state['histories'].setdefault(qid,[]).append(history)
        try:
            scope=context.get('math_review_scope')
            if not replies and not context.get('structured_output_correction') and not (scope and len(scope['question_ids'])==1):barrier.wait(timeout=5)
            time.sleep(.005)
            if bad=='transport' and qid=='Q2':return httpx.Response(429,json={'error':{'message':'offline transport failure'}})
            if tools and not replies:
                output=[{'type':'function_call','call_id':qid+'-calc','name':'algebra_batch',
                    'arguments':json.dumps({'operations':[{'kind':'evaluate','expression':'x^2','variables':['x'],
                        'substitutions':{'x':2 if qid=='Q1' else 3}}]})}]
            else:
                if tools:
                    assert len(replies)==1 and replies[0]['call_id']==qid+'-calc'
                    assert all(m.get('call_id','').startswith(qid) for m in replies)
                value=part(sample[0],qid,'unknown' if bad=='unknown' and qid=='Q2' else 'pass',
                    {'stage':'math','target':'Q2','detail':'端点取等约束写反，须回数学Agent更正'} if bad=='math' and qid=='Q2' and not state['repairs'] else None,
                    condition_ids=context['parallel_review_scope']['condition_ids'])
                value['passages']={p['id']:{'verdict':'pass','evidence':'核对绑定的原候选句子成立'} for p in context['literal_passages']}
                if bad=='passage' and qid=='Q2' and not state['repairs']:
                    value['passages']['Q2:domain'].update(verdict='issue',evidence='原句所述端点条件与代回已知表达式的实际结果矛盾，需要更正原文')
                if bad=='missing' and qid=='Q2':value['questions']={}
                if bad=='condition' and qid=='Q1':value['conditions']={}
                output=[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(flat_review(value),ensure_ascii=False)}]}]
            return httpx.Response(200,json={'status':'completed','output':output,'usage':{'input_tokens':10,'output_tokens':20}})
        finally:
            with lock:state['active']-=1
    cfg=replace(settings,parallel_review=True,compact_tools=True,review_responses=True,max_calls=12,incremental_math_review=incremental)
    runner=Runner(cfg,job[1],lambda s,a:DeepSeek(s,a,httpx.MockTransport(handler)),MemoryCache,renderer)
    return runner,source,candidate,state


@pytest.mark.parametrize('tools',[False,True])
def test_real_native_requests_have_two_lanes_private_histories_full_context_and_strict_merge(settings,job,sample,tools):
    runner,source,candidate,state=setup_review(settings,job,sample,tools=tools)
    value=runner.review(source,candidate,{'status':'pass','samples':[]})
    assert value.verdict=='pass' and state['peak']==2
    assert [q.id for q in value.questions]==['Q1','Q2']
    assert runner.model_calls==(4 if tools else 2)
    assert runner.shared_budget.snapshot()['usage']['complete']
    assert len(runner.parallel_review_rounds)==1
    check_rounds(runner.parallel_review_rounds,source,candidate,runner.request,[])
    assert len(list((job[2]/'review-agents/round-01').glob('Q*/audit.json')))==2


@pytest.mark.parametrize('bad',['unknown','math'])
def test_unknown_and_math_objections_survive_parent_review(settings,job,sample,bad):
    runner,source,candidate,state=setup_review(settings,job,sample,bad=bad)
    value=runner.review(source,candidate,{})
    if bad=='unknown':assert value.verdict=='needs_input' and value.questions[1].verdict=='unknown'
    else:assert value.verdict=='revise' and value.issues[0].stage=='math'
    assert state['peak']==2


@pytest.mark.parametrize('bad',['missing','condition'])
def test_missing_coverage_is_not_a_partial_success_or_serial_fallback(settings,job,sample,bad):
    runner,source,candidate,state=setup_review(settings,job,sample,bad=bad)
    with pytest.raises(ValueError):runner.review(source,candidate,{})
    assert len(state['calls'])==3 and not runner.parallel_review_rounds
    assert runner.shared_budget.snapshot()['cancelled']


def test_merge_retains_unknown_conditions_and_every_distinct_issue(sample):
    source=Source.model_validate(sample[0]);parts={q:part(sample[0],q) for q in ['Q1','Q2']}
    parts['Q2']['conditions']={}
    parts['Q1']['conditions']['C1']={'verdict':'unknown','evidence':'原图该条件未能确认'}
    parts['Q1']['verdict']='needs_input'
    issue={'stage':'source','target':'C1','detail':'须返回原题独立核对'}
    parts['Q2']['issues']=[issue];parts['Q2']['verdict']='revise'
    merged=merge_parts(source,['Q1','Q2'],parts)
    assert merged['verdict']=='needs_input' and merged['conditions']['C1']['verdict']=='unknown'
    assert merged['issues']==[issue]
    for bad in [{}, {'Q1':parts['Q1']},{**parts,'Q3':parts['Q1']}]:
        with pytest.raises(ValueError):merge_parts(source,['Q1','Q2'],bad)


def test_cache_rounds_reject_missing_parts_changed_input_and_corrupted_merge(settings,job,sample):
    runner,source,candidate,_=setup_review(settings,job,sample)
    runner.review(source,candidate,{})
    for change in ['missing','merged','input','binding']:
        records=copy.deepcopy(runner.parallel_review_rounds);request=copy.deepcopy(runner.request)
        if change=='missing':del records[0]['parts']['Q2']
        if change=='merged':records[0]['merged']['conditions']['C1']['evidence']='偷偷换核验结果'
        if change=='input':request['text']='另一道题'
        if change=='binding':records[0]['binding']='bad'
        with pytest.raises(ValueError):check_rounds(records,source,candidate,request,[])
    with pytest.raises(ValueError):check_rounds([],source,candidate,runner.request,[])


def test_actual_screenshots_keep_original_tab_indices_in_each_private_request(settings,job,sample):
    from PIL import Image
    runner,source,candidate,state=setup_review(settings,job,sample)
    (job[2]/'output').mkdir()
    for i in range(2):Image.new('RGB',(100,100),(i*150,0,0)).save(job[2]/'output'/f'tab-{i:02d}.png')
    runner.review(source,candidate,{})
    assert state['screenshots']=={'Q1':['实际JSXGraph截图：tab-00'],'Q2':['实际JSXGraph截图：tab-01']}


def test_transport_failure_cancels_without_retry_or_new_full_review(settings,job,sample):
    from math_agent.provider import ModelError
    runner,source,candidate,state=setup_review(settings,job,sample,bad='transport')
    with pytest.raises(ModelError):runner.review(source,candidate,{})
    assert sorted(state['calls'])==['Q1','Q2'] and runner.model_calls==2
    assert runner.shared_budget.snapshot()['cancelled']
    assert not runner.parallel_review_rounds


def test_parallel_review_configuration_and_cache_are_explicit(settings):
    from math_agent.cache import key_for
    cfg=replace(settings,parallel_review=True,compact_tools=True)
    assert key_for(cfg,{'text':'','images':[]})!=key_for(settings,{'text':'','images':[]})
    for values in [{'compact_tools':False},{'reference_mode':True},{'review_plan':True},{'incremental_review':True}]:
        with pytest.raises(ValueError):replace(cfg,**values)


def test_condition_responsibilities_cover_global_compound_and_reused_scopes(sample):
    from math_agent.parallel_review import condition_plan
    source=Source.model_validate(sample[0])
    base=source.conditions[0]
    source.conditions.extend([base.model_copy(update={'id':'C2','question_ids':['Q2']}),
        base.model_copy(update={'id':'C3','question_ids':['Q1','Q2']}),
        base.model_copy(update={'id':'C4','question_ids':['Q1']})])
    assert condition_plan(source,['Q1','Q2'])=={'Q1':['C1','C3','C4'],'Q2':['C2','C3']}
    # A later proof-only revision still requires ALL original conditions.
    assert condition_plan(source,['Q2'])=={'Q2':['C1','C2','C3','C4']}


def test_two_balanced_reviewers_cover_all_questions_and_original_group_opinions(sample):
    from math_agent.parallel_review import review_groups,group_conditions,split_group
    from math_agent.review_passages import passages
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    for n in range(3,6):
        source.questions.append(source.questions[-1].model_copy(update={'id':f'Q{n}'}))
        candidate.solutions.append(candidate.solutions[-1].model_copy(update={'question_id':f'Q{n}'}))
        candidate.spec['tabs'].append(copy.deepcopy(candidate.spec['tabs'][-1]))
    ids=[q.id for q in source.questions];groups=review_groups(candidate,ids)
    assert len(groups)==2
    assert sorted(q for g in groups for q in g['question_ids'])==ids
    assert all(len(g['question_ids'])>=2 for g in groups)
    parts={}
    for group in groups:
        raw={'verdict':'pass','conditions':{c:{'verdict':'pass','evidence':'条件来源完整核对'} for c in group_conditions(source,ids,group['question_ids'])},
            'questions':{q:{'verdict':'pass','evidence':q+'独立逐问核对'} for q in group['question_ids']},'issues':[],
            'passages':{p['id']:{'verdict':'pass','evidence':'原文正确'} for p in passages(candidate,group['question_ids'])}}
        parts.update(split_group(source,candidate,ids,group,flat_review(raw)))
        broken=copy.deepcopy(raw);broken['questions'].pop(group['question_ids'][-1])
        with pytest.raises(ValueError):split_group(source,candidate,ids,group,flat_review(broken))
    merged=merge_parts(source,ids,parts)
    assert merged['verdict']=='pass' and list(merged['questions'])==ids


@pytest.mark.parametrize('repair,incremental',[(False,False),(True,False),(True,True)])
def test_whole_langgraph_publish_cache_and_math_repair_keep_all_gates(settings,job,sample,repair,incremental):
    runner,source,candidate,state=setup_review(settings,job,sample,bad='math' if repair else None,incremental=incremental)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['bootstrap']==(['source','solve','math_repair'] if repair else ['source','solve'])
    assert runner.model_calls==(6 if incremental else 7 if repair else 4)
    cached=runner.cache.data;assert len(cached['parallel_review_rounds'])==(2 if repair else 1)
    assert not report['deferred_reviews']['pending']
    store=job[0]
    for corrupt in [False,True]:
        new_id,path=store.prepare();write_json(path/'request.json',runner.request)
        store.enqueue(new_id);store.claim()
        new=Runner(runner.settings,new_id,runner.provider_factory,MemoryCache,renderer)
        new.cache.data=copy.deepcopy(cached)
        if corrupt:new.cache.data['parallel_review_rounds'][-1]['parts'].pop('Q2')
        new.run()
        assert new.model_calls==0
        assert store.get(new_id)['status']==('failed' if corrupt else 'completed')


def test_literal_issue_under_root_pass_really_returns_to_math_agent_and_requires_new_review(settings,job,sample):
    runner,source,candidate,state=setup_review(settings,job,sample,bad='passage')
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['bootstrap']==['source','solve','math_repair'] and runner.model_calls==7
    rounds=runner.parallel_review_rounds
    assert rounds[0]['merged']['verdict']=='revise'
    assert any(i['stage']=='math' and i['target']=='Q2:domain' for i in rounds[0]['merged']['issues'])
    assert rounds[-1]['merged']['verdict']=='pass'
