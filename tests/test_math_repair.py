import copy
import pytest
from math_agent.contracts import Source,Candidate,MathRepair
from math_agent.pipeline import Runner,canonical_page
from test_pipeline import provider,MemoryCache,renderer


def test_math_repair_keeps_geometry_but_updates_display_and_evidence(settings,job,sample):
    source=Source.model_validate(sample[0]);old=Candidate.model_validate(sample[1])
    fixed=copy.deepcopy(sample[1]['solutions']);fixed[0]['result']='修正后的结论'
    runner=Runner(settings,job[1],provider([{'solutions':fixed}],[]),MemoryCache,renderer)
    value=runner.repair_math(source,old,[{'stage':'math','target':'Q1','detail':'错误'}])
    assert value.solutions[0].result=='修正后的结论'
    assert value.spec['tabs'][0]['conclusion']=='修正后的结论'
    assert [t['board'] for t in value.spec['tabs']]==[t['board'] for t in old.spec['tabs']]
    assert old.solutions[0].result!='修正后的结论'
    assert runner.pending_math_objections==[{'stage':'math','target':'Q1','detail':'错误'}]
    assert (job[2]/'evidence-ledger.json').exists()
    with pytest.raises(ValueError):MathRepair.model_validate({'solutions':fixed,'spec':old.spec})
