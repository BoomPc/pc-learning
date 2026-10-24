import copy
import json
import threading
import time
from dataclasses import replace
import httpx
import pytest
from math_agent.pipeline import Runner
from math_agent.provider import DeepSeek
from test_pipeline import MemoryCache, renderer


def setup_run(settings,job,sample,concurrency=2,dependencies=False,unknown=False,bad_basis=False,review_issue=False,max_calls=12,tool_feedback=False,diagram_defects=0,missing_basis=False,patch_basis='C1',bad_condition=False,fix_dependencies=False,native_solve=False,schema_wrapper=False):
    source,candidate,review=copy.deepcopy(sample)
    for s in candidate['solutions']:
        for st in s['steps']:st['basis_ids']=['C1']
    if dependencies:candidate['solutions'][1]['steps'][0]['basis_ids']=['Q1:S1']
    if bad_basis:candidate['solutions'][1]['steps'][0]['basis_ids']=['Q1:S1']
    if bad_condition:
        source['problem_text']+='\n仅第一问的局部条件'
        source['conditions'].append({'id':'C2','text':'仅第一问的局部条件','origin':'question_text','image_ids':[],'question_ids':['Q1']})
        candidate['solutions'][1]['condition_ids'].append('C2')
        candidate['solutions'][1]['steps'][0]['basis_ids']=['C2']
    metadata={'groups':[{'question_ids':[q['id']], 'depends_on':['Q1'] if dependencies and q['id']=='Q2' else [],
                         'dependency_status':'unknown' if unknown else 'known'} for q in source['questions']]}
    raw={s['question_id']:{'proof':{k:v for k,v in s.items() if k!='question_id'},
         'board':candidate['spec']['tabs'][i]['board'],**({'controls':candidate['spec']['tabs'][i]['controls']} if 'controls' in candidate['spec']['tabs'][i] else {})}
         for i,s in enumerate(candidate['solutions'])}
    for qid in list(raw)[:diagram_defects]:
        raw[qid]['board']['objects'].append({'id':'invalidFormula','kind':'functiongraph',
                                           'expression':'-x^2-3x-2','domain':[-3,3]})
    if missing_basis:raw['Q2']['proof']['steps'][0]['basis_ids']=[]
    state={'active':0,'peak':0,'calls':[],'branch_contexts':{},'review_calls':0,'diagram_calls':0}
    lock=threading.Lock();barrier=threading.Barrier(2)
    def handler(request):
        body=json.loads(request.content)
        native=request.url.path.endswith('/responses')
        if native:
            body['messages']=[{**m,'content':([{'type':'text','text':p['text']} if p['type']=='input_text' else p
                             for p in m['content']] if isinstance(m['content'],list) else m['content'])}
                             for m in body['input'] if m.get('type')=='message']
        # Image observations add a later user message; task scope stays in the
        # original structured user message, not in the crop attachment.
        user=next(m for m in body['messages'] if m['role']=='user' and isinstance(m['content'],list)
                  and m['content'][0].get('text','').startswith('{"task":'))
        context=json.loads(user['content'][0]['text'])['context']
        use_tool=False
        if 'output_question_ids' in context:
            ids=context['output_question_ids']
            instruction=next(m['content'] for m in body['messages'] if m['role']=='system')
            # A branch sees one scoped output contract, never two conflicting
            # full-page/scoped schemas followed by an override instruction.
            assert instruction.count('"$defs":')==1
            marker='返回JSON Schema：'
            contract=json.JSONDecoder().raw_decode(instruction.split(marker,1)[1])[0]
            assert contract['required']==ids
            assert set(contract['properties'])==set(ids)
            assert 'basis_ids' in contract['$defs']['Step']['required']
            assert contract['$defs']['Step']['properties']['basis_ids']['minItems']==1
            if ids==['Q2']:
                from jsonschema import validate,ValidationError
                reference={'proof':{'steps':[{'basis_ids':['Q1:S1']}]}}
                from test_compact_tools import proof_constraints
                constraint=proof_constraints(contract,'Q2')
                if dependencies:validate(reference,constraint)
                else:
                    with pytest.raises(ValidationError):validate(reference,constraint)
            assert 'JSON实例' in instruction and '覆盖前面整题' not in instruction
            with lock:
                state['active']+=1;state['peak']=max(state['peak'],state['active']);state['calls'].append(tuple(ids))
                state['branch_contexts'][ids[0]]=context
            try:
                if tool_feedback and not any(m['role']=='tool' for m in body['messages']):use_tool=True
                if tool_feedback and not use_tool:
                    assert any(m.get('reasoning_content')=='private branch reasoning' for m in body['messages'])
                    if tool_feedback=='image':
                        observed=json.loads(next(m['content'] for m in body['messages'] if m['role']=='tool'))
                        assert observed['ok'] and observed['image_id']=='I1' and observed['role']=='question'
                        assert observed['pixel_box']==[30,24,270,216]
                        assert any(p.get('type')=='image_url' for m in body['messages'] if m['role']=='user'
                                   and isinstance(m['content'],list) and m['content'][0].get('text','').startswith('局部原图观察')
                                   for p in m['content'])
                if concurrency==2 and not dependencies and not unknown and not (schema_wrapper and context.get('structured_output_correction')):
                    barrier.wait(timeout=3)
                time.sleep(.01)
                result={q:raw[q] for q in ids}
                if schema_wrapper and ids==['Q1'] and not context.get('structured_output_correction'):
                    result=contract
            finally:
                with lock:state['active']-=1
        elif 'submission_patch_schema' in context:
            state['calls'].append(('citation_patch',))
            fields=context['submission_patch_schema']['properties']['updates']['properties']
            updates={}
            for qid,field in fields.items():
                names=set(field['properties']);assert names<= {'step_basis','proof','board'}
                update={}
                if 'step_basis' in names:update['step_basis']={'S1':[patch_basis]}
                if 'proof' in names:
                    proof=copy.deepcopy(raw[qid]['proof'])
                    if fix_dependencies:
                        proof['condition_ids']=['C1'];proof['steps'][0]['basis_ids']=['C1']
                    update['proof']=proof
                if 'board' in names:
                    board=copy.deepcopy(raw[qid]['board'])
                    next(o for o in board['objects'] if o['id']=='invalidFormula')['expression']='-x^2-3*x-2'
                    update['board']=board
                updates[qid]=update
            result={'updates':updates}
        elif 'allowed_tabs' in context:
            state['diagram_calls']+=1
            assert context['allowed_tabs']==list(range(diagram_defects))
            assert all(i['stage']=='diagram' for i in context['feedback'])
            result={'edits':[{'tab':i,'upsert':[{'id':'invalidFormula','kind':'functiongraph',
                'expression':'-x^2-3*x-2','domain':[-3,3]}]} for i in range(diagram_defects)]}
        elif 'candidate' in context:
            state['review_calls']+=1
            result={'verdict':'revise' if review_issue else 'pass',
                    'conditions':{c['id']:{'verdict':'pass','evidence':'all input conditions checked'} for c in source['conditions']},
                    'questions':{q['id']:{'verdict':'issue' if review_issue and q['id']=='Q2' else 'pass','evidence':'proof checked'} for q in source['questions']},
                    'issues':[{'stage':'math','target':'Q2','detail':'边界仍有遗漏'}] if review_issue else []}
        elif 'source' in context:
            state['calls'].append(('whole',));result=raw
        else:
            result={'source':source,'parallel_plan':metadata}
        tool_name='view_image_region' if tool_feedback=='image' else 'algebra_batch'
        tool_args=({'image_id':'I1','bbox':[.1,.1,.9,.9],'reason':'核对原题点名'} if tool_feedback=='image' else
                   {'operations':[{'op':'simplify','variables':[],'expression':'1+1'}]})
        message=({'role':'assistant','content':'核对计算','reasoning_content':'private branch reasoning',
            'tool_calls':[{'id':'tool-1','type':'function','function':{'name':tool_name,'arguments':json.dumps(tool_args)}}]}
            if use_tool else {'role':'assistant','content':json.dumps(result,ensure_ascii=False)})
        if native:
            assert not use_tool
            return httpx.Response(200,json={'status':'completed','output':[{'type':'message','role':'assistant',
                'content':[{'type':'output_text','text':message['content']}]}],
                'usage':{'input_tokens':10,'output_tokens':20}})
        return httpx.Response(200,json={'choices':[{'message':message,'finish_reason':'tool_calls' if use_tool else 'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':20}})
    cfg=replace(settings,parallel_questions=True,compact_tools=True,question_concurrency=concurrency,max_calls=max_calls,max_repairs=0,solve_responses=native_solve)
    factory=lambda settings,audit:DeepSeek(settings,audit,httpx.MockTransport(handler))
    runner=Runner(cfg,job[1],factory,MemoryCache,renderer)
    return runner,state


@pytest.mark.parametrize('concurrency',[1,2])
def test_real_pipeline_merges_branches_then_requires_full_review(settings,job,sample,concurrency):
    runner,state=setup_run(settings,job,sample,concurrency)
    runner.run()
    report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['peak']==concurrency and state['review_calls']==1
    assert report['model_calls_this_job']==4
    result=json.loads((job[2]/'candidate.json').read_text())
    assert [s['question_id'] for s in result['solutions']]==['Q1','Q2']
    assert runner.shared_budget.snapshot()['usage']['complete']
    assert len(list((job[2]/'question-agents/round-01').glob('G*/audit.json')))==2


def test_dependent_branch_only_receives_finished_dependencies(settings,job,sample):
    # Explicit serial experiment still exercises dependency handoff.
    runner,state=setup_run(settings,job,sample,dependencies=True,concurrency=1)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['peak']==1
    assert state['branch_contexts']['Q1']['completed_dependencies']==[]
    assert state['branch_contexts']['Q2']['completed_dependencies'][0]['question_id']=='Q1'


def test_two_lane_chain_uses_whole_question_without_speculative_branch_calls(settings,job,sample):
    runner,state=setup_run(settings,job,sample,dependencies=True,concurrency=2)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['calls']==[('whole',)] and not state['branch_contexts']
    assert state['review_calls']==1 and report['model_calls_this_job']==3
    plan=json.loads((job[2]/'question-plan.json').read_text())
    assert plan['eligible'] and not plan['execution']['has_overlap']
    assert plan['execution']['strategy']=='whole_question'
    assert not (job[2]/'question-agents').exists()


def test_unknown_dependency_stays_whole_without_speculative_paid_fallback(settings,job,sample):
    runner,state=setup_run(settings,job,sample,unknown=True)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert not state['branch_contexts'] and state['calls']==[('whole',)]
    assert report['model_calls_this_job']==3


def test_undeclared_cross_branch_reference_cannot_publish(settings,job,sample):
    runner,state=setup_run(settings,job,sample,bad_basis=True)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and '未声明' in report['error']
    assert not state['review_calls']
    assert job[0].get(job[1])['status']=='failed'


def test_missing_citation_recovers_once_then_runs_full_review(settings,job,sample):
    runner,state=setup_run(settings,job,sample,missing_basis=True)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['review_calls']==1 and report['model_calls_this_job']==5
    assert sorted(state['calls'])==sorted([('Q1',),('Q2',),('citation_patch',)])
    actual=json.loads((job[2]/'candidate.json').read_text())
    from math_agent.contracts import Candidate
    baseline=Candidate.model_validate(sample[1]).model_dump()['solutions']
    for solution in baseline:
        for step in solution['steps']:step['basis_ids']=['C1']
    assert actual['solutions']==baseline


def test_citation_repair_cannot_introduce_undeclared_dependency(settings,job,sample):
    runner,state=setup_run(settings,job,sample,missing_basis=True,patch_basis='Q1:S1')
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and '未声明' in report['error']
    assert not state['review_calls'] and not (job[2]/'output/result.html').exists()


@pytest.mark.parametrize('options',[
    {'bad_basis':True},{'bad_condition':True},{'bad_condition':True,'unknown':True},
    {'bad_condition':True,'diagram_defects':1},
])
def test_dependency_defects_repair_only_reported_questions_then_full_review(settings,job,sample,options):
    runner,state=setup_run(settings,job,sample,fix_dependencies=True,**options)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['review_calls']==1 and state['calls'].count(('citation_patch',))==1
    actual=json.loads((job[2]/'candidate.json').read_text())
    # No branch or whole solve replay, only the single reported correction.
    assert len(state['calls'])==(2 if options.get('unknown') else 3)
    assert all(step['basis_ids']==['C1'] for solution in actual['solutions'] for step in solution['steps'])
    assert actual['solutions'][0]['result']==sample[1]['solutions'][0]['result']
    if not options.get('diagram_defects'):
        for before,after in zip(sample[1]['spec']['tabs'],actual['spec']['tabs']):
            from math_agent.jsxgraph.spec import Board
            assert Board.model_validate(before['board']).model_dump()==Board.model_validate(after['board']).model_dump()


def test_parallel_cache_restores_and_rechecks_original_dependency_plan(settings,job,sample):
    from math_agent.storage import write_json
    runner,state=setup_run(settings,job,sample)
    runner.run();cached=copy.deepcopy(runner.cache.data)
    assert cached['question_plan_metadata']==runner.question_plan_metadata
    cached['candidate']['solutions'][1]['steps'][0]['basis_ids']=['Q1:S1']
    other_id,path=job[0].prepare();write_json(path/'request.json',{'text':'离线测试题','images':[],'force':False})
    write_json(path/'image-roles.json',{});job[0].enqueue(other_id);job[0].claim()
    other=Runner(runner.settings,other_id,runner.provider_factory,MemoryCache,renderer);other.cache.data=cached
    prior_calls=len(state['calls']);other.run();report=json.loads((path/'report.json').read_text())
    assert report['status']=='failed' and '未声明' in report['error']
    assert len(state['calls'])==prior_calls and not (path/'output/result.html').exists()


def test_false_review_pass_cannot_bypass_dependency_gate(monkeypatch,settings,job,sample):
    from math_agent.contracts import Source,Candidate,Review
    runner,state=setup_run(settings,job,sample,bad_basis=True)
    s=Source.model_validate(sample[0]);c=Candidate.model_validate(sample[1])
    for solution in c.solutions:
        for step in solution.steps:step.basis_ids=['C1']
    c.solutions[1].steps[0].basis_ids=['Q1:S1']
    runner.question_plan_metadata={'groups':[{'question_ids':[qid],'depends_on':[],'dependency_status':'known'} for qid in ['Q1','Q2']]}
    monkeypatch.setattr('math_agent.flow.execute_graph',lambda *_:{'source':s,'candidate':c,'review':Review.model_validate(sample[2])})
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and '未声明' in report['error'] and runner.cache.data is None
    assert not state['calls'] and not (job[2]/'output/result.html').exists()


def test_review_objection_is_not_overridden_by_branch_success(settings,job,sample):
    runner,state=setup_run(settings,job,sample,review_issue=True)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and '修复次数' in report['error']
    assert state['review_calls']==1


def test_source_children_and_review_share_one_call_cap(settings,job,sample):
    runner,state=setup_run(settings,job,sample,max_calls=3)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and report['model_calls_this_job']==3
    assert state['review_calls']==0


def test_request_can_finish_after_deadline_but_cannot_publish(settings,job,sample):
    from math_agent.parallel_budget import ParallelBudget
    source=sample[0];calls=[];now=[0.0]
    def handler(r):
        calls.append(1);now[0]=2.0
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':json.dumps(source)},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':17,'completion_tokens':23}})
    cfg=replace(settings,parallel_questions=True,compact_tools=True)
    runner=Runner(cfg,job[1],lambda s,a:DeepSeek(s,a,httpx.MockTransport(handler)),MemoryCache,renderer)
    runner.shared_budget=ParallelBudget(12,timeout_seconds=1,clock=lambda:now[0])
    runner.provider.shared_budget=runner.shared_budget
    runner.run()
    report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='failed' and len(calls)==1
    assert not (job[2]/'output/result.html').exists()
    assert runner.shared_budget.snapshot()['usage']['known_completion_tokens']==23


def test_parallel_settings_do_not_enable_unsupported_routes(settings):
    with pytest.raises(ValueError):replace(settings,parallel_questions=True)
    with pytest.raises(ValueError):replace(settings,parallel_questions=True,compact_tools=True,reference_mode=True)
    with pytest.raises(ValueError):replace(settings,question_concurrency=3)


def test_two_agent_tool_loops_preserve_private_history_and_global_usage(settings,job,sample):
    runner,state=setup_run(settings,job,sample,tool_feedback=True)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['peak']==2 and report['model_calls_this_job']==6
    assert runner.shared_budget.snapshot()['usage']['reported_calls']==6
    tools=[r for r in report['audit'] if r['kind']=='tool']
    assert len(tools)==2 and {r['branch_id'] for r in tools}=={'G1','G2'}


def test_parallel_agents_receive_real_uploaded_crop_pixels(settings,job,sample):
    from PIL import Image
    from math_agent.storage import write_json
    Image.new('RGB',(300,240),(50,100,150)).save(job[2]/'I1.png')
    write_json(job[2]/'request.json',{'text':'离线测试题','images':[
        {'id':'I1','role':'question','file':'I1.png','sha256':'fixture'}],'force':True})
    runner,state=setup_run(settings,job,sample,tool_feedback='image')
    runner.run()
    report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['peak']==2 and state['review_calls']==1
    tools=[r for r in report['audit'] if r['kind']=='tool' and r['name']=='view_image_region']
    assert len(tools)==2 and all(r['result']['ok'] for r in tools)
    crops=list((job[2]/'question-agents/round-01').glob('G*/image-views/view-01.png'))
    assert len(crops)==2
    for path in crops:
        with Image.open(path) as crop:
            assert crop.getpixel((0,0))==(50,100,150)


def test_source_branches_and_review_share_only_input_pixel_preparation(settings,job,sample):
    from PIL import Image
    from math_agent.storage import write_json
    Image.new('RGB',(16,5000),'white').save(job[2]/'I1.png')
    write_json(job[2]/'request.json',{'text':'离线测试题','images':[
        {'id':'I1','role':'question','file':'I1.png','sha256':'fixture'}],'force':True})
    runner,state=setup_run(settings,job,sample)
    runner.run()
    report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert report['model_calls_this_job']==4 and state['review_calls']==1
    stats=runner.provider.pixel_cache.snapshot()
    # solve_views also supplies small unmodified strips. Those intentionally
    # bypass storage; only the oversized original needs encoded tile reuse.
    assert stats['entries']==1 and stats['hits']==3 and stats['misses']>=1


@pytest.mark.parametrize('defects',[1,2])
def test_parallel_expression_errors_use_one_scoped_diagram_repair(settings,job,sample,defects):
    runner,state=setup_run(settings,job,sample,diagram_defects=defects)
    runner.run()
    report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['diagram_calls']==1 and state['review_calls']==1
    assert sorted(state['calls'])==[('Q1',),('Q2',)]
    final=json.loads((job[2]/'candidate.json').read_text())
    for i,solution in enumerate(final['solutions'],1):
        branch=job[2]/f'question-agents/round-01/G{i}'
        original=json.loads(next(branch.glob('model-*-solve.json')).read_text())[f'Q{i}']['proof']
        assert {k:v for k,v in solution.items() if k!='question_id'}==original
    errors=[r for r in report['audit'] if r['kind']=='contract_error']
    assert len(errors)==1 and 'invalid decimal literal' in errors[0]['detail']
    assert report['model_calls_this_job']==5


@pytest.mark.parametrize('options',[
    {'bad_basis':True,'fix_dependencies':True},
    {'bad_condition':True,'fix_dependencies':True},
    {'missing_basis':True},
    {'schema_wrapper':True},
])
def test_native_complete_invalid_schema_still_requires_bounded_local_recovery(settings,job,sample,options):
    runner,state=setup_run(settings,job,sample,native_solve=True,**options)
    runner.run();report=json.loads((job[2]/'report.json').read_text())
    assert report['status']=='completed',report.get('error')
    assert state['review_calls']==1 and report['model_calls_this_job']==5
    assert any(r['kind']=='schema_candidate' for r in report['audit'])
    assert runner.shared_budget.snapshot()['usage']['complete']
    if options.get('schema_wrapper'):
        assert state['calls'].count(('Q1',))==2 and state['calls'].count(('Q2',))==1
    else:
        assert state['calls'].count(('citation_patch',))==1
        assert state['calls'].count(('Q1',))==state['calls'].count(('Q2',))==1
