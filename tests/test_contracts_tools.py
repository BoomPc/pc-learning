import copy
import pytest
from math_agent.contracts import Source, Candidate, Review, check_source, check_candidate, check_review
from math_agent.rendering import strict_spec
from math_agent.tools import dispatch, geometry_check


def test_answer_image_cannot_be_source(sample):
    source = Source.model_validate(sample[0])
    source.conditions[0].origin = "question_image"; source.conditions[0].image_ids = ["I1"]
    with pytest.raises(ValueError, match="答案图"):
        check_source(source, [{"id": "I1", "role": "answer"}])


def test_review_missing_question_or_unknown_cannot_pass(sample):
    source = Source.model_validate(sample[0]); review = Review.model_validate(sample[2])
    review.questions.pop()
    with pytest.raises(ValueError, match="缺项"): check_review(review, source)
    review = Review.model_validate(sample[2]); review.conditions[0].verdict = "unknown"
    with pytest.raises(ValueError, match="未知"): check_review(review, source)


def test_question_order_and_problem_text_are_immutable(sample):
    source = Source.model_validate(sample[0]); candidate = Candidate.model_validate(sample[1])
    candidate.solutions.reverse()
    with pytest.raises(ValueError, match="顺序"): check_candidate(candidate, source)
    candidate.solutions.reverse(); candidate.spec["problem_text"] = "删掉限制条件"
    with pytest.raises(ValueError, match="题干"): check_candidate(candidate, source)


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(dynamic_script="alert(1)"),
    lambda s: s["tabs"][0]["board"]["objects"][2].update(expression="__import__('os').system('id')"),
    lambda s: s["tabs"][0]["board"]["objects"].append({"id":"bad","kind":"segment","parents":["Missing","A"]}),
    lambda s: s["tabs"][1]["controls"]["slider"].update(min=5),
    lambda s: s["tabs"][0]["board"]["objects"].append({"id":"A","kind":"point","coords":[9,9]}),
    lambda s: s["tabs"][0]["board"].update(bounding_box=[0,0,0,0]),
])
def test_unsafe_or_inconsistent_drawing_is_rejected(sample, mutation):
    spec = copy.deepcopy(sample[1]["spec"]); mutation(spec)
    with pytest.raises(Exception): strict_spec(spec)


def test_real_symbolic_tool_and_code_injection():
    value = dispatch("algebra_batch", {"operations": [{"op": "solve", "variables": ["x"], "equations": ["x**2-2*x=0"]}]})
    assert value["ok"] and {s["x"] for s in value["results"][0]["solutions"]} == {"0", "2"}
    value = dispatch("algebra_batch", {"operations": [{"op": "simplify", "variables": [], "expression": "__import__('os').system('id')"}]})
    assert value["ok"] is False
    with pytest.raises(ValueError): dispatch("shell", {"command": "id"})


def test_geometry_and_degeneracy():
    points = {"A": [0, 0], "B": [2, 0], "C": [1, 0], "D": [1, 2]}
    value = geometry_check(points, [{"relation": "on_segment", "points": ["A", "B", "C"]}, {"relation": "perpendicular", "points": ["A", "B", "C", "D"]}])
    assert value["ok"]
    assert not geometry_check(points, [{"relation": "perpendicular", "points": ["A", "A", "C", "D"]}])["ok"]
    assert not geometry_check(points, [{"relation": "on_segment", "points": ["A", "C", "B"]}])["ok"]


def test_local_knowledge_search():
    value = dispatch("knowledge_search", {"query": "抛物线 三角形 面积 最大值"})
    assert value["matches"] and "不是本题答案" in value["note"]


@pytest.mark.parametrize('scale', [1e-6,1,1e4])
def test_collinearity_with_nearly_coincident_points_and_segment_endpoint(scale):
    import math
    from itertools import permutations
    points={'A':[0,0], 'B':[3*scale,math.sqrt(3)*scale],
            'D':[(3-4e-15)*scale,(math.sqrt(3)-2e-15)*scale]}
    for ids in permutations(points):
        assert geometry_check(points,[{'relation':'collinear','points':list(ids)}])['ok']
    points['P']=[1e-12*scale,-1e-12*scale]
    assert geometry_check(points,[{'relation':'on_segment','points':['A','B','P']}])['ok']
    points['P']=[scale,scale]
    assert not geometry_check(points,[{'relation':'collinear','points':['A','B','P']}])['ok']
    assert not geometry_check(points,[{'relation':'on_segment','points':['A','B','P']}])['ok']
    # A zero-length segment still cannot establish perpendicularity.
    assert not geometry_check(points,[{'relation':'perpendicular','points':['A','A','B','D']}])['ok']


def test_failed_inspection_feedback_does_not_lose_failure_after_many_passes():
    from math_agent.pipeline import failed_inspection_detail
    import json
    passed=[{'matches_expected':True,'observed':{'A':[0,0]},'padding':'x'*200} for _ in range(20)]
    failed={'relation':'collinear','points':['A','B','C'],'matches_expected':False}
    detail=json.loads(failed_inspection_detail({'ok':True,'probes':[{'tab':0,'checks':passed},{'tab':3,'checks':[failed]}]}))
    assert detail['failed_count']==1
    assert detail['failed_checks']==[{'tab':3,'parameter':None,'check':failed}]


def test_mixed_source_reports_condition_and_forbidden_image(sample):
    source = Source.model_validate(sample[0])
    condition = source.conditions[0]
    condition.image_ids = ["I1", "I2"]
    with pytest.raises(ValueError) as error:
        check_source(source, [{"id":"I1","role":"question"},{"id":"I2","role":"answer"}])
    message = str(error.value)
    assert condition.id in message and "I2" in message and "I1" in message
    assert "不得仅改图片编号" in message
    assert condition.image_ids == ["I1", "I2"]
