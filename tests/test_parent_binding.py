import copy
import pytest
from math_agent.parent_binding import bind_parent_roles
from math_agent.rendering import strict_spec


def page(sample,kind,parents):
    spec=copy.deepcopy(sample[1]['spec']);spec['tabs']=spec['tabs'][:1]
    spec['tabs'][0]['board']={'viewport':'fit_points','objects':[{'id':'A','kind':'point','coords':[0.,0.]},
        {'id':'B','kind':'point','coords':[2.,0.]},{'id':'P','kind':'point','coords':[1.,3.]},
        {'id':'AB','kind':'line','parents':['A','B']},{'id':'X','kind':kind,'parents':parents}]}
    spec['tabs'][0].pop('controls',None)
    return spec


@pytest.mark.parametrize('kind,wrong,right',[
 ('perpendicularpoint',['AB','P'],['P','AB']),('reflection',['AB','P'],['P','AB']),
 ('parallel',['P','AB'],['AB','P']),('perpendicular',['P','AB'],['AB','P'])])
def test_unique_roles_bind_to_native_signature_without_mutating_input(sample,kind,wrong,right):
    raw=page(sample,kind,wrong);before=copy.deepcopy(raw)
    with pytest.raises(ValueError):strict_spec(raw)
    bound,changes=bind_parent_roles(raw)
    assert raw==before and changes[0]['before']==wrong
    assert bound['tabs'][0]['board']['objects'][-1]['parents']==right
    strict_spec(bound);again,changes=bind_parent_roles(bound);assert again==bound and not changes


@pytest.mark.parametrize('kind,parents',[('perpendicularpoint',['A','B']),('reflection',['A','missing'])])
def test_ambiguous_or_missing_roles_still_fail_strict_validation(sample,kind,parents):
    raw=page(sample,kind,parents);bound,changes=bind_parent_roles(raw)
    assert not changes and raw==bound
    with pytest.raises(ValueError):strict_spec(bound)


def test_rotation_order_and_direction_are_never_inferred(sample):
    raw=page(sample,'rotation',['P','A'])
    raw['tabs'][0]['board']['objects'][-1].update(direction='clockwise',degrees=60.)
    bound,changes=bind_parent_roles(raw);assert bound==raw and not changes
