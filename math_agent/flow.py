"""StateGraph orchestration with browser evidence before independent review."""
from __future__ import annotations
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langsmith import tracing_context
from .contracts import Source, Candidate, Review
from .rendering import RenderError
from .storage import write_json


class State(TypedDict, total=False):
    source: Source
    candidate: Candidate
    review: Review
    observation: dict
    feedback: list[dict]
    repairs: int
    next: str
    entry: str


def execute_graph(runner, initial=None):
    from .pipeline import NeedsInput

    def source(state):
        runner.audit('graph_node', {'node':'source'})
        return {'source':runner.extract(state.get('feedback')), 'observation':{}}

    def solve(state):
        runner.audit('graph_node', {'node':'solve'})
        return {'candidate':runner.solve(state['source'],state.get('feedback'),state.get('candidate'))}

    def math_repair(state):
        runner.audit('graph_node', {'node':'math_repair'})
        return {'candidate':runner.repair_math(state['source'],state['candidate'],state['feedback']), 'observation':{}}

    def diagram(state):
        runner.audit('graph_node', {'node':'diagram'})
        ids=[q.id for q in state['source'].questions]
        targets={i.get('target') for i in state['feedback']}
        allowed={ids.index(q) for q in targets} if targets and targets<=set(ids) else None
        return {'candidate':runner.solve(state['source'],state['feedback'],state['candidate'],'diagram',allowed_tabs=allowed)}

    def observe(state):
        runner.audit('graph_node', {'node':'observe'})
        write_json(runner.directory/'candidate.json',state['candidate'].model_dump())
        try:
            from .native_constructions import require
            require(state['source'],state['candidate'])
            observation = runner.observe(state['candidate'])
            return {'observation':observation,'next':'review'}
        except RenderError as exc:
            issues=getattr(exc,'issues',None)
            return {'observation':{'status':'fail','error':str(exc)},'next':'repair',
                    'feedback':([{'stage':'diagram','target':i['question_id'],'detail':i['detail']} for i in issues]
                                if issues else [{'stage':'diagram','target':'browser','detail':str(exc)}])}

    def review(state):
        runner.audit('graph_node', {'node':'review'})
        value = runner.review(state['source'],state['candidate'],state['observation'])
        write_json(runner.directory/'review.json',value.model_dump())
        if value.verdict == 'needs_input':
            raise NeedsInput('；'.join(i.detail for i in value.issues) or '原题存在未确定信息')
        return {'review':value,'next':END if value.verdict=='pass' else 'repair',
                'feedback':[i.model_dump() for i in value.issues]}

    def repair(state):
        count = state.get('repairs',0)
        if count >= runner.settings.max_repairs:
            raise ValueError('修复次数已用完，未发布网页。最后异议：'+str(state['feedback'])[:2200])
        stages = {i['stage'] for i in state['feedback']}
        next_stage = 'source' if 'source' in stages else 'math_repair' if 'math' in stages else 'diagram'
        runner.audit('repair', {'stage':next_stage,'attempt':count+1,'feedback':state['feedback']})
        return {'repairs':count+1,'next':next_stage}

    graph = StateGraph(State)
    for name, node in [('source',source),('solve',solve),('math_repair',math_repair),('diagram',diagram),('observe',observe),('review',review),('repair',repair)]:
        graph.add_node(name,node)
    graph.add_edge(START,initial.get('entry','observe') if initial else 'source'); graph.add_edge('source','solve')
    graph.add_edge('math_repair','observe'); graph.add_edge('solve','observe'); graph.add_edge('diagram','observe')
    graph.add_conditional_edges('observe',lambda s:s['next'],{'review':'review','repair':'repair'})
    graph.add_conditional_edges('review',lambda s:s['next'],{'repair':'repair',END:END})
    graph.add_conditional_edges('repair',lambda s:s['next'],{'source':'source','math_repair':'math_repair','diagram':'diagram'})
    compiled = graph.compile()
    (runner.directory/'agent-graph.mmd').write_text(compiled.get_graph().draw_mermaid())
    with tracing_context(enabled=False):
        return compiled.invoke(initial or {'repairs':0,'feedback':[]}, {'recursion_limit':8+runner.settings.max_repairs*6, 'callbacks':[]})
