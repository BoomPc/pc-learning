from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .text_evidence import quote_in_text


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Condition(Strict):
    quote: str = Field(default="", max_length=2000, description="文字题设的逐字原文摘录，须出现在problem_text；text可作释义，图示条件留空")
    question_ids: list[str] = Field(default_factory=list, max_length=12, description="适用的小问编号；空列表仅表示整题通用条件")
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=2000)
    origin: Literal["question_text", "question_image", "explicit_diagram_mark"]
    image_ids: list[str] = Field(max_length=10)


class Question(Strict):
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=4000)


class NativeConstruction(Strict):
    id: str = Field(pattern=r'^N[1-9][0-9]*$')
    question_ids: list[str] = Field(min_length=1,max_length=12)
    point: str = Field(min_length=1,max_length=40,description='原文新引入的派生点名；不是渲染器内部ID')
    kind: Literal['rotation','translation','intersection','midpoint','reflection','perpendicularpoint']
    parents: list[str] = Field(min_length=1,max_length=2,description='原文点名或曲线名。rotation=[原点,中心]；translation=[原点]；intersection=[两曲线名]；midpoint=[两端点]；reflection/perpendicularpoint=[原点,直线名]。直线可写AB，函数曲线可写y₁。')
    condition_ids: list[str] = Field(min_length=1,max_length=10)
    quote: str = Field(min_length=1,max_length=2000,description='包含此派生点的连续原文，必须出现在problem_text和所引用文字条件中；不从答案图添加')


class Source(Strict):
    topic_family: Literal["rotation_translation", "parabola", "other", "unknown"] = "unknown"
    title: str = Field(min_length=1, max_length=100)
    problem_text: str = Field(min_length=1, max_length=20000)
    conditions: list[Condition] = Field(min_length=1, max_length=100)
    questions: list[Question] = Field(min_length=1, max_length=12)
    reference_summary: str = Field(max_length=15000)
    uncertainties: list[str] = Field(max_length=30)
    native_constructions: list[NativeConstruction] = Field(default_factory=list,max_length=60,
        description='原题明确引入的新派生点及构造关系；这是需独立复核的读题结果，不是新增题设或已证事实。')


class Step(Strict):
    basis_ids: list[str] = Field(default_factory=list, max_length=30, description="依据条件C编号或已经出现的步骤Qn:Sm；推导仍需复核")
    premise: str = Field(min_length=1, max_length=3000)
    rule: str = Field(min_length=1, max_length=1000)
    conclusion: str = Field(min_length=1, max_length=3000)


class Solution(Strict):
    question_id: str = Field(min_length=1, max_length=40)
    result: str = Field(min_length=1, max_length=4000)
    steps: list[Step] = Field(min_length=1, max_length=40)
    cases: list[str] = Field(max_length=30)
    domain_and_boundaries: str = Field(min_length=1, max_length=3000)
    condition_ids: list[str] = Field(max_length=100)


class ReviewPreparation(Strict):
    covered_questions: list[str] = Field(min_length=1,max_length=12)
    probes: list[dict] = Field(max_length=16,description="待执行的inspect_scene查询；不得填写expected")
    algebra_operations: list[dict] = Field(max_length=12,description="待执行的algebra_batch.operations；没有需要时空列表")


class MathRepair(Strict):
    solutions: list[Solution] = Field(min_length=1, max_length=12)


class Candidate(Strict):
    solutions: list[Solution] = Field(min_length=1, max_length=12)
    # JSXGraph 声明式对象契约在独立渲染进程中验证。
    spec: dict


class Check(Strict):
    id: str = Field(min_length=1, max_length=40)
    verdict: Literal["pass", "issue", "unknown"]
    evidence: str = Field(min_length=1, max_length=3000)


class Issue(Strict):
    stage: Literal["source", "math", "diagram"]
    target: str = Field(min_length=1, max_length=100)
    detail: str = Field(min_length=1, max_length=3000)


class Review(Strict):
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra={
        "allOf":[{"if":{"properties":{"verdict":{"const":"revise"}}},
                  "then":{"properties":{"issues":{"minItems":1}}}},
                 {"if":{"properties":{"verdict":{"const":"pass"}}},
                  "then":{"properties":{"issues":{"maxItems":0}}}}]})
    verdict: Literal["pass", "revise", "needs_input"]
    conditions: list[Check] = Field(max_length=100)
    questions: list[Check] = Field(max_length=12)
    issues: list[Issue] = Field(max_length=30)


def exact_ids(actual, expected, label):
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError(f"{label}缺项、重复或出现未知编号")


def check_source(source: Source, images: list[dict]):
    exact_ids([c.id for c in source.conditions], [c.id for c in source.conditions], "条件")
    exact_ids([q.id for q in source.questions], [q.id for q in source.questions], "小问")
    question_images = {i["id"] for i in images if i["role"] == "question"}
    for c in source.conditions:
        if c.quote and (c.origin != "question_text" or not quote_in_text(c.quote,source.problem_text)):
            raise ValueError(f"条件{c.id}.quote须为题干中的逐字文字，不能引用图示外观或编造摘录；不匹配的quote={c.quote!r}。请逐字对照problem_text的对应片段，保留原题数学符号，明确修正不一致字符而非重复原quote。")
        if not set(c.question_ids) <= {q.id for q in source.questions}:
            raise ValueError(f"条件{c.id}的question_ids引用了不存在的小问{sorted(set(c.question_ids)-{q.id for q in source.questions})}；仅允许questions中实际列出的编号{[q.id for q in source.questions]}。若拆成子问，父问条件必须显式列举各子问编号，不可保留不存在的父编号。")
        if not set(c.image_ids) <= question_images:
            raise ValueError(f"条件{c.id}的image_ids含禁止的参考答案图或未知来源{sorted(set(c.image_ids)-question_images)}；题设仅允许原题图片{sorted(question_images)}。请重新对照原题：若此条件仅来自参考答案的辅助构造，移至reference_summary，不得作为conditions；不得仅改图片编号来伪装来源。")
        if c.origin != "question_text" and not c.image_ids:
            raise ValueError("图片来源的条件必须列出图片编号")
    from .native_constructions import validate_source
    validate_source(source)


def candidate_issues(candidate: Candidate, source: Source):
    exact_ids([s.question_id for s in candidate.solutions], [q.id for q in source.questions], "解答小问")
    if [s.question_id for s in candidate.solutions] != [q.id for q in source.questions]:
        raise ValueError("解答顺序必须与题目小问一致")
    conditions = {c.id for c in source.conditions}
    issues=[]
    for solution in candidate.solutions:
        if not set(solution.condition_ids) <= conditions:
            issues.append({'stage':'math','question_id':solution.question_id,'path':'proof.condition_ids',
                'detail':f"{solution.question_id}解答引用了不存在的题设条件{sorted(set(solution.condition_ids)-conditions)}；condition_ids只能引用原题条件{sorted(conditions)}，步骤Qn:Sm仅能出现在basis_ids中，不得改写原条件编号"})
    available = set(conditions)
    for solution in candidate.solutions:
        for index, step in enumerate(solution.steps, 1):
            if not set(step.basis_ids) <= available:
                issues.append({'stage':'math','question_id':solution.question_id,'path':f'proof.steps.{index-1}.basis_ids',
                    'detail':f"{solution.question_id}:S{index}.basis_ids中的{sorted(set(step.basis_ids)-available)}不可引用；步骤依据只能引用已知条件或已出现的推导编号，不能引用未来步骤或待证目标；不得仅删除依据规避核验"})
            available.add(f"{solution.question_id}:S{index}")
    if len(candidate.spec.get("tabs", [])) != len(source.questions):
        raise ValueError("网页小问数与原题不一致")
    if candidate.spec.get("problem_text") != source.problem_text:
        raise ValueError("网页题干必须逐字保留已提取题干")
    from .function_consistency import collect as function_checks
    issues.extend(function_checks(candidate.solutions)['issues'])
    return issues


def check_candidate(candidate: Candidate, source: Source):
    issues=candidate_issues(candidate,source)
    if issues:raise ValueError('；'.join(i['detail'] for i in issues))


def check_review(review: Review, source: Source):
    exact_ids([c.id for c in review.conditions], [c.id for c in source.conditions], "条件核验")
    exact_ids([q.id for q in review.questions], [q.id for q in source.questions], "小问核验")
    if review.verdict == "pass" and (review.issues or any(c.verdict != "pass" for c in review.conditions + review.questions)):
        raise ValueError("存在异议或未知项时不能宣告核验通过")
    if review.verdict == "revise" and not review.issues:
        raise ValueError("verdict=revise要求issues至少一项，当前为空。请重新确认：若全部核验项pass且确无未决问题，应由你明确提交verdict=pass；若仍需修复则给出具体issues；若不确定则needs_input并保留unknown。不得编造异议或为了格式一致忽略真实问题。")


class AssertionDecision(Strict):
    assertion_id: str = Field(pattern=r"^A[1-9][0-9]*$")
    question_id: str | None = None
    object_ids: list[str] = Field(default_factory=list, max_length=30)
    verdict: Literal["invalid_check", "real_issue", "unresolved"]
    basis_ids: list[str] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=20, max_length=4000)
    issue: Issue | None

class ObjectionScope(Strict):
    question_id: str = Field(min_length=1)
    object_ids: list[str] = Field(min_length=1, max_length=30)
    basis_ids: list[str] = Field(min_length=1, max_length=30, description="仅限适用于此question_id的条件/推导，不混入其他小问局部条件")


class TextualDecision(Strict):
    assertion_id: str = Field(pattern=r"^R[1-9][0-9]*$")
    verdict: Literal["invalid_check", "real_issue", "unresolved"]
    scopes: list[ObjectionScope] = Field(min_length=1, max_length=12, description="逐个列出该意见涉及的小问、该小问真实对象、该小问适用依据；撤销意见也不可省略")
    reason: str = Field(min_length=20, max_length=4000)
    issue: Issue | None


class Adjudication(Strict):
    decisions: list[TextualDecision | AssertionDecision] = Field(min_length=1, max_length=100)
    reviewed: Review | None = None
