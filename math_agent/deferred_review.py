"""Version-bound pending review work; postponement never grants publication."""
import copy
from typing import Literal
from pydantic import Field
from .contracts import Strict, Issue, ObjectionScope, exact_ids
from .review_reuse import digest


class DeferredResolution(Strict):
    id: str
    origin_hash: str
    verdict: Literal['invalid_check', 'resolved_by_revision', 'real_issue', 'unresolved']
    scopes: list[ObjectionScope] = Field(min_length=1, max_length=12)
    reason: str = Field(min_length=20, max_length=4000)
    issue: Issue | None


class DeferredVerdict(Strict):
    current_hash: str
    resolutions: list[DeferredResolution] = Field(min_length=1, max_length=100)


def content_binding(source, candidate, request):
    return digest({'source':source.model_dump(), 'candidate':candidate.model_dump(),
        'text':request['text'], 'images':[{k:i[k] for k in ('id','role','sha256')} for i in request['images']]})


class PendingReviews:
    def __init__(self):
        self.pending=[]
        self.receipts=[]

    def load(self, data):
        if set(data)!={'pending','receipts'} or not isinstance(data['pending'],list) or not isinstance(data['receipts'],list):
            raise ValueError('暂存复核存档格式错误')
        self.pending=copy.deepcopy(data['pending']);self.receipts=copy.deepcopy(data['receipts'])
        for b in self.pending:
            value={k:v for k,v in b.items() if k!='sha256'}
            if digest(value)!=b.get('sha256'):raise ValueError('暂存复核存档哈希错误')
        for r in self.receipts:DeferredVerdict.model_validate({k:v for k,v in r.items() if k!='origin_hashes'})

    def add(self, source, candidate, observation, request, failures, review):
        record={'source':source.model_dump(), 'candidate':candidate.model_dump(),
            'observation':copy.deepcopy(observation), 'failures':copy.deepcopy(failures),
            'review':review.model_dump(), 'binding':content_binding(source,candidate,request)}
        record['sha256']=digest(record)
        if not any(r['sha256']==record['sha256'] for r in self.pending):self.pending.append(record)

    def payload(self, source, candidate, request):
        bundles=copy.deepcopy(self.pending)
        for b in bundles:
            h=b.pop('sha256')
            if digest(b)!=h:raise ValueError('暂存复核记录哈希不匹配')
            b['sha256']=h
        return {'current_hash':content_binding(source,candidate,request), 'deferred_bundles':bundles,
            'obligations':[{'id':f'D{i+1}:{f["id"]}', 'origin_hash':b['sha256'], 'failure':copy.deepcopy(f)}
                for i,b in enumerate(bundles) for f in b['failures']]}

    def validate(self, raw, payload, source, candidate, ledger):
        from .evidence import validate_basis
        result=DeferredVerdict.model_validate(raw)
        if result.current_hash!=payload['current_hash']:raise ValueError('暂存裁决不属于当前题设/证明/图形版本')
        exact_ids([r.id for r in result.resolutions],[o['id'] for o in payload['obligations']], '暂存检查逐条裁决')
        by_id={o['id']:o for o in payload['obligations']}
        bundles={b['sha256']:b for b in payload['deferred_bundles']}
        current={s.question_id:i for i,s in enumerate(candidate.solutions)}
        for r in result.resolutions:
            obligation=by_id[r.id]
            if r.origin_hash!=obligation['origin_hash']:raise ValueError('暂存裁决的原版本哈希不匹配')
            if r.verdict=='resolved_by_revision':
                old=bundles[r.origin_hash]
                if old['binding']==payload['current_hash']:raise ValueError('版本未修改，不可宣称已由修订解决')
                f=obligation['failure']
                if f.get('kind')=='proof_guard':
                    tab=f['tab'];old_solution=old['candidate']['solutions'][tab];qid=old_solution['question_id']
                    if qid in current:
                        drawing=lambda t:{k:t.get(k) for k in ('board','controls')}
                        same_drawing=digest(drawing(old['candidate']['spec']['tabs'][tab]))==digest(drawing(candidate.spec['tabs'][current[qid]]))
                        if same_drawing and old_solution==candidate.solutions[current[qid]].model_dump():
                            raise ValueError('相关小问证明与图形均未改变，不能声称该证明反例已由修订解决')
                # A failing geometric assertion cannot be repaired by prose changes alone.
                if f.get('kind') not in {'invalid_query','proof_guard'} and 'tab' in f:
                    tab=f['tab']
                    old_tab=old['candidate']['spec']['tabs'][tab]
                    q=old['candidate']['solutions'][tab]['question_id']
                    if q in current and digest({k:old_tab.get(k) for k in ('board','controls')})==digest({k:candidate.spec['tabs'][current[q]].get(k) for k in ('board','controls')}):
                        raise ValueError('相关图形未改变，不能把真实失败断言称为修图已解决；须核对原断言是否有效')
            if (r.verdict=='real_issue') != (r.issue is not None):raise ValueError('真实问题必须给issue，其余裁决不得附带issue')
            for scope in r.scopes:
                if scope.question_id not in current:raise ValueError('暂存裁决须绑定当前实际小问')
                objects={o['id'] for o in candidate.spec['tabs'][current[scope.question_id]]['board']['objects']}
                if not set(scope.object_ids)<=objects:raise ValueError('暂存裁决引用当前图形不存在的对象')
                validate_basis(ledger,scope.basis_ids,scope.question_id)
        return result

    def commit(self, result, payload):
        if {b['sha256'] for b in self.pending}!={b['sha256'] for b in payload['deferred_bundles']}:
            raise ValueError('暂存裁决对应的待审集合已变化，不能提交旧结果')
        if any(r.verdict=='unresolved' for r in result.resolutions):raise ValueError('暂存检查仍有未决项，不能发布')
        self.receipts.append({'current_hash':payload['current_hash'],
            'origin_hashes':[b['sha256'] for b in payload['deferred_bundles']],**result.model_dump()})
        settled={b['sha256'] for b in payload['deferred_bundles']}
        self.pending=[b for b in self.pending if b['sha256'] not in settled]

    def dump(self):return {'pending':copy.deepcopy(self.pending),'receipts':copy.deepcopy(self.receipts)}
