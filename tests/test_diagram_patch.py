import copy
import pytest
from math_agent.contracts import Candidate
from math_agent.diagram_patch import apply_patch


def test_patch_preserves_proof_and_unrelated_tabs(sample):
    prior=Candidate.model_validate(sample[1]); original=copy.deepcopy(prior.model_dump())
    patch={'edits':[{'tab':0,'upsert':[{'id':'added','kind':'segment','parents':['A','B']}]}]}
    result=apply_patch(patch,prior)
    assert prior.model_dump()==original and result.solutions==prior.solutions
    assert result.spec['tabs'][1]==prior.spec['tabs'][1]
    assert result.spec['tabs'][0]['board']['objects'][:-1]==prior.spec['tabs'][0]['board']['objects']
    assert result.spec['tabs'][0]['board']['objects'][-1]['id']=='added'

@pytest.mark.parametrize('patch',[
 {'edits':[{'tab':0,'cases':[]}]},
 {'edits':[{'tab':0,'remove':['missing']}]},
 {'edits':[{'tab':0,'upsert':[{'id':'added','kind':'segment','parents':['A','missing']}]}]},
 {'edits':[{'tab':0},{'tab':0}]},
 {'edits':[{'tab':10}]},
 {'edits':[{'tab':0}],'solutions':[]},
])
def test_bad_patch_rejected_atomically(sample,patch):
    prior=Candidate.model_validate(sample[1]); original=prior.model_dump()
    with pytest.raises(ValueError):apply_patch(patch,prior)
    assert prior.model_dump()==original
