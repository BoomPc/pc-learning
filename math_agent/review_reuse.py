"""Job-local review reuse; immutable mathematics plus newly reviewed drawing changes."""
import copy
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import Field
from .contracts import Strict, Check, Issue, Review, check_review, exact_ids

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def binding(source,candidate,request,directory):
    images=[]
    for img in request['images']:
        path=(directory/img['file']).resolve()
        if not path.is_relative_to(directory.resolve()):raise ValueError('图片路径越界')
        images.append({'id':img['id'],'role':img['role'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    package=Path(__file__).resolve().parent
    engine=digest({str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [package/'rendering.py',*(package/'jsxgraph').rglob('*')] if p.is_file() and '__pycache__' not in p.parts})
    return digest({'engine':engine,'source':source.model_dump(),'solutions':[s.model_dump() for s in candidate.solutions],
        'text':request['text'],'images':images})

class Resolution(Strict):
    id: str
    verdict: Literal['resolved','unresolved','unknown']
    evidence: str = Field(min_length=1,max_length=2000)

class DrawingReview(Strict):
    verdict: Literal['pass','revise','needs_input']
    questions: list[Check] = Field(max_length=12)
    resolutions: list[Resolution] = Field(max_length=30)
    issues: list[Issue] = Field(max_length=30)

class Snapshot:
    def __init__(self,source,candidate,review,observation,request,directory):
        check_review(review,source)
        from .scene_tools import fingerprint
        if observation.get("status")!="pass" or observation.get("spec_sha256")!=fingerprint(candidate.spec):
            raise ValueError("没有当前候选页面的成功浏览器观察，不能创建复用证据")
        if (review.verdict=='needs_input' or any(i.stage!='diagram' for i in review.issues)
                or any(c.verdict!='pass' for c in review.conditions+review.questions)):
            raise ValueError('存在数学/题设异议或未知项，不能复用数学复核')
        self.binding=binding(source,candidate,request,directory)
        self.candidate=candidate.model_copy(deep=True)
        self.review=review.model_copy(deep=True)
        self.observation=copy.deepcopy(observation)
        self.certificate=digest({'binding':self.binding,'review':review.model_dump()})

    def delta(self,source,candidate,request,directory):
        if self.binding!=binding(source,candidate,request,directory):return None
        old=self.candidate.spec; new=candidate.spec
        if len(old['tabs'])!=len(new['tabs']):return None
        if {k:v for k,v in old.items() if k!='tabs'}!={k:v for k,v in new.items() if k!='tabs'}:return None
        tabs=[i for i,(a,b) in enumerate(zip(old['tabs'],new['tabs'])) if a!=b]
        if not tabs:return None
        # Every changed tab, including text/controls/dependent geometry, is rechecked in full.
        return {'certificate':self.certificate,'changed_tabs':tabs,
            'changed_questions':[source.questions[i].id for i in tabs],
            'objections':[{'id':f'I{i+1}',**issue.model_dump()} for i,issue in enumerate(self.review.issues)],
            'previous_review':self.review.model_dump(),
            'previous_tabs':[{'tab':i,'drawing':old['tabs'][i]} for i in tabs],
            'scope':'同一任务中的已审数学版本；哈希只证明内容一致，不是形式化证明。新发现的数学/题设问题仍须提出。'}

    def merge(self,raw,delta,source):
        value=DrawingReview.model_validate(raw)
        exact_ids([q.id for q in value.questions],delta['changed_questions'],'变化画板复核')
        exact_ids([d.id for d in value.resolutions],[o['id'] for o in delta['objections']],'原修图异议核对')
        unfinished=[d for d in value.resolutions if d.verdict!='resolved']
        if value.verdict=='pass' and (unfinished or value.issues or any(q.verdict!='pass' for q in value.questions)):
            raise ValueError('变化画板、原异议或新问题未解决，不能pass')
        if unfinished and not value.issues:raise ValueError('未解决异议须保留在issues')
        if any(d.verdict=='unknown' for d in value.resolutions) and value.verdict!='needs_input':
            raise ValueError('异议仍未知须needs_input')
        checks={q.id:q for q in value.questions}
        merged=self.review.model_copy(deep=True)
        merged.verdict=value.verdict; merged.issues=value.issues
        for i,old in enumerate(merged.questions):
            if old.id in checks:
                new=checks[old.id].model_copy(deep=True)
                new.evidence='数学复核沿用证书'+self.certificate+'；本次变化画板复核：'+new.evidence
                merged.questions[i]=new
        check_review(merged,source)
        return merged


def query_tool(delta):
    """A changed-drawing reviewer asks facts; judgments belong in its final review."""
    from .scene_tools import INSPECT
    tool=copy.deepcopy(INSPECT)
    probe=tool['function']['parameters']['properties']['probes']['items']
    probe['properties']['tab']={'type':'integer','enum':delta['changed_tabs']}
    check=probe['properties']['checks']['items']
    check['properties'].pop('expected',None)
    tool['function']['description']='只读查询变化画板的真实几何事实；不能填写expected，不重新检查未变化画板。根据holds与原题在最终复核中判断是否有问题。'
    return tool


def check_certificate_chain(source,review,records):
    """Preserve the historical review behind certificate references, including cache replay."""
    import re
    known=set()
    def references(value):
        return set(re.findall(r'数学复核沿用证书([0-9a-f]{64})',json.dumps(value,ensure_ascii=False)))
    for record in records:
        old=Review.model_validate(record['review']);check_review(old,source)
        if old.verdict=='needs_input' or any(i.stage!='diagram' for i in old.issues) or any(c.verdict!='pass' for c in old.conditions+old.questions):
            raise ValueError('缓存证书包含未通过的数学/题设复核')
        if references(record['review'])-known:raise ValueError('复核证书的前序证据缺失')
        expected=digest({'binding':record['binding'],'review':record['review']})
        if expected!=record['sha256']:raise ValueError('复核证书内容与摘要不符')
        known.add(expected)
    if references(review.model_dump())-known:raise ValueError('最终复核引用了未保存的数学证书')
