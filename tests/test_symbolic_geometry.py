import pytest
from math_agent.tools import dispatch


def test_exact_rotation_translation_and_symbolic_identity():
    r=dispatch('symbolic_geometry',{'variables':['t'],'points':{'O':[1,2],'P':[3,2]},'constructions':[
        {'id':'R','kind':'rotation','parents':['P','O'],'degrees':90,'direction':'clockwise'},
        {'id':'T','kind':'translation','parents':['R'],'vector':['t',0]},
        {'id':'M','kind':'midpoint','parents':['R','T']}],
        'measurements':[{'kind':'distance_squared','points':['R','T']},{'kind':'dot','points':['O','P','O','R']}]})
    assert r['ok'] and r['points']['R']==['1','0'] and r['points']['M']==['t/2 + 1','0']
    assert r['measurements'][0]['value']=='t**2' and r['measurements'][1]['zero'] is True


def test_rotation_sign_and_radicals_are_not_float_approximations():
    r=dispatch('symbolic_geometry',{'points':{'O':[0,0],'P':[2,0]},'constructions':[
        {'id':'R','kind':'rotation','parents':['P','O'],'degrees':60,'direction':'counterclockwise'}],
        'measurements':[{'kind':'oriented_area2','points':['O','P','R']}]})
    assert r['ok'] and r['points']['R']==['1','sqrt(3)'] and r['measurements'][0]['value']=='2*sqrt(3)'


@pytest.mark.parametrize('change', ['injection','missing','duplicate','wrong_fields','complex'])
def test_invalid_geometry_cannot_return_success(change):
    args={'points':{'O':[0,0],'P':[1,0]},'constructions':[],'measurements':[]}
    if change=='injection':args['points']['P']=["__import__('os').system('id')",0]
    if change=='complex':args['points']['P']=['sqrt(-1)',0]
    if change in {'missing','duplicate','wrong_fields'}:
        args['constructions']=[{'id':'O' if change=='duplicate' else 'R','kind':'rotation','parents':['X' if change=='missing' else 'P','O'],'degrees':90,'direction':'clockwise'}]
        if change=='wrong_fields':args['constructions'][0]['vector']=[1,2]
    assert dispatch('symbolic_geometry',args)['ok'] is False


def test_rotation_domain_is_explicit():
    args={'variables':['a'],'points':{'O':[0,0],'P':[1,0]},'constructions':[{'id':'R','kind':'rotation','parents':['P','O'],'degrees':'a','direction':'clockwise'}],'measurements':[]}
    r=dispatch('symbolic_geometry',args)
    assert r['ok'] and 'a >= 0' in r['domain_restrictions']
    args['constructions'][0]['degrees']=-90
    assert dispatch('symbolic_geometry',args)['ok'] is False


def test_angle_measurement_checks_vertex_without_relabeling_triangle():
    args={'points':{'A':[0,0],'B':[3,0],'C':[0,'sqrt(3)']},'constructions':[],
        'measurements':[{'kind':'angle_cosine','points':['B','A','C']}, {'kind':'angle_cosine','points':['A','B','C']}]}
    r=dispatch('symbolic_geometry',args)
    assert r['ok'] and [m['value'] for m in r['measurements']]==['0','sqrt(3)/2']
    args['measurements']=[{'kind':'angle_cosine','points':['A','A','C']}]
    assert dispatch('symbolic_geometry',args)['ok'] is False
