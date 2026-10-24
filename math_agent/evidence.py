"""Scoped, versioned evidence: observations and model claims are not proven facts."""
import copy
from .tools import definition

READ_EVIDENCE = definition('read_evidence', '读取本题证据记录。given为原题转写（仍可能误读），derived为待复核推导，question为求证/求解目标，不能当成已知。不得把其他小问的局部条件直接搬过来。',
    {'ids': {'type':'array','items':{'type':'string'},'maxItems':30}}, ['ids'])


def build_ledger(source, candidate=None):
    entries = {}
    all_questions = [q.id for q in source.questions]
    for c in source.conditions:
        entries[c.id] = {'id':c.id,'kind':'given','text':c.text,'question_ids':c.question_ids or all_questions,
                         'origin':c.origin,'quote':c.quote,'image_ids':c.image_ids,'status':'transcribed_not_independently_verified'}
    for q in source.questions:
        entries[q.id] = {'id':q.id,'kind':'question','text':q.text,'question_ids':[q.id],'status':'goal_not_premise'}
    if candidate:
        for solution in candidate.solutions:
            for i, step in enumerate(solution.steps, 1):
                name = f'{solution.question_id}:S{i}'
                entries[name] = {'id':name,'kind':'derived','text':step.conclusion,'premise':step.premise,
                    'rule':step.rule,'basis_ids':step.basis_ids,'question_ids':[solution.question_id],
                    'status':'model_claim_not_proof_certificate'}
    return {'entries':entries, 'note':'记录来源和适用范围，不表示内容已经数学证明。跨小问引用必须说明条件是否仍成立。'}


def read_ledger(ledger, ids):
    if any(i not in ledger['entries'] for i in ids): raise ValueError('证据编号不存在')
    if not ids: return {'ok':True,'index':[{'id':v['id'],'kind':v['kind'],'question_ids':v['question_ids']} for v in ledger['entries'].values()]}
    return {'ok':True,'entries':[copy.deepcopy(ledger['entries'][i]) for i in ids]}


def validate_basis(ledger, ids, question_id=None):
    if not ids: raise ValueError('断言必须引用题设或待核验推导的basis_ids；探索关系请省略expected')
    for name in ids:
        item = ledger['entries'].get(name)
        if not item or item['kind'] in {'question','hypothesis'}: raise ValueError('断言依据必须是条件C编号或推导Qn:Sm，不能把待证目标Q编号当已知')
        if question_id and question_id not in item['question_ids']:
            raise ValueError(f'证据{name}不适用于{question_id}；需要在当前小问给出适用性推导，或先作不含expected的查询')


def assertion_basis_index(ledger,solutions):
    """Expose the existing inspection guard's exact scopes, never prove claims."""
    result={}
    for tab,solution in enumerate(solutions):
        qid=solution.question_id
        allowed=[]
        for name in ledger['entries']:
            try:validate_basis(ledger,[name],qid)
            except ValueError:continue
            allowed.append(name)
        result[str(tab)]={'question_id':qid,'available_basis_ids':allowed}
    return result

RECORD_HYPOTHESIS = definition('record_hypothesis', '记录当前小问的待检验猜想及下一步验证计划；记录不是证明，不能直接作为必须成立的断言依据。',
    {'question_id':{'type':'string'},'claim':{'type':'string','minLength':1,'maxLength':2000},
     'basis_ids':{'type':'array','items':{'type':'string'},'maxItems':30},
     'next_check':{'type':'string','minLength':1,'maxLength':1500}}, ['question_id','claim','basis_ids','next_check'])


def record_hypothesis(ledger, question_id, claim, basis_ids, next_check):
    if ledger['entries'].get(question_id,{}).get('kind') != 'question': raise ValueError('猜想必须属于现有小问')
    if basis_ids: validate_basis(ledger,basis_ids,question_id)
    count=sum(e['kind']=='hypothesis' for e in ledger['entries'].values())
    if count>=30: raise ValueError('猜想记录达到上限')
    name=f'H{count+1}'
    ledger['entries'][name]={'id':name,'kind':'hypothesis','text':claim,'question_ids':[question_id],
        'basis_ids':basis_ids,'next_check':next_check,'status':'unverified_do_not_use_as_premise'}
    return {'ok':True,'entry':copy.deepcopy(ledger['entries'][name])}
