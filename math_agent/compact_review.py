"""Bind review records to source IDs rather than asking the model to renumber lists."""
import copy
from typing import Literal
from pydantic import Field
from .contracts import Strict,Issue,Check,Review,exact_ids

class ReviewShapeError(ValueError):
    """ID coverage is invalid; no new mathematical observation can repair that encoding."""

class Record(Strict):
    verdict: Literal['pass','issue','unknown']
    evidence: str = Field(min_length=1,max_length=3000)

class KeyedReview(Strict):
    verdict: Literal['pass','revise','needs_input']
    conditions: dict[str,Record]
    questions: dict[str,Record]
    issues: list[Issue] = Field(max_length=30)

class PassageRecord(Record):
    quote: str = Field(min_length=1,max_length=12000)

class PassageReview(KeyedReview):
    passages: dict[str,PassageRecord]

class _EncodingPassageRecord(Record):
    # Syntax recovery preserves the missing member as missing. Only the later
    # candidate-bound validator may attach that known original-text metadata.
    quote: str | None = Field(default=None,min_length=1,max_length=12000)

class _EncodingPassageReview(KeyedReview):
    passages: dict[str,_EncodingPassageRecord]

class FlatRecord(Record):
    quote: str = Field(max_length=12000)

class FlatReview(Strict):
    verdict: Literal['pass','revise','needs_input']
    records: dict[str,FlatRecord]
    issues: list[Issue] = Field(max_length=30)

class _EncodingFlatRecord(Record):
    quote: str | None = Field(default=None,max_length=12000)

class _EncodingFlatReview(Strict):
    verdict: Literal['pass','revise','needs_input']
    records: dict[str,_EncodingFlatRecord]
    issues: list[Issue] = Field(max_length=30)

def output_schema(source,passages=None,flat=False):
    if flat:
        schema=FlatReview.model_json_schema();props={}
        for name in ('conditions','questions'):
            for c in source[name]:
                node=copy.deepcopy(schema['$defs']['FlatRecord'])
                node['description']=('原题条件来源核对' if name=='conditions' else '该问全部证明与图文关系核验')+'：'+c['text']+'；quote可留空，仅记录原文副本，不修改题设'
                props[c['id']]=node
        for item in passages or []:
            node=copy.deepcopy(schema['$defs']['FlatRecord'])
            node['properties']['quote']['enum']=[item['text']]
            node['description']=item['question_id']+' '+item['field']+'：quote逐字引用候选原文（包括错误），判断原句，不能默改后判通过'
            if item['id'] in props:raise ValueError('原文核验编号与C/Q编号冲突')
            props[item['id']]=node
        schema['properties']['records']={'type':'object','additionalProperties':False,'required':list(props),'properties':props}
        return schema
    schema=(PassageReview if passages is not None else KeyedReview).model_json_schema()
    for name in ('conditions','questions'):
        schema['properties'][name]={'type':'object','additionalProperties':False,
            'required':[c['id'] for c in source[name]],
            'properties':{c['id']:{'$ref':'#/$defs/Record','description':c['text']} for c in source[name]}}
    if passages is not None:
        props={}
        for item in passages:
            node=copy.deepcopy(schema['$defs']['PassageRecord'])
            node['properties']['quote']['enum']=[item['text']]
            node['description']=item['question_id']+' '+item['field']+'：逐字引用候选原文，再判断这句原文是否正确，不得默改成正确句后判通过'
            props[item['id']]=node
        schema['properties']['passages']={'type':'object','additionalProperties':False,'required':list(props),'properties':props}
    return schema

def unpack(raw,source):
    value=KeyedReview.model_validate(raw)
    try:
        exact_ids(list(value.conditions),[c.id for c in source.conditions],'条件核验')
        exact_ids(list(value.questions),[q.id for q in source.questions],'小问核验')
    except ValueError as exc:
        raise ReviewShapeError(str(exc)) from exc
    return Review(verdict=value.verdict,
        conditions=[Check(id=c.id,**value.conditions[c.id].model_dump()) for c in source.conditions],
        questions=[Check(id=q.id,**value.questions[q.id].model_dump()) for q in source.questions],issues=value.issues)


def repair_encoding(raw):
    """Recover member-wrapper punctuation only, retaining every scalar in exact order.

    This is NOT a general JSON repairer: no invented keys, values, dropped issues,
    guessed strings, or duplicate-key resolution. Only explicit keyed review records
    with individually valid JSON values can be re-encoded.
    """
    import json
    def invalid_constant(value):raise ValueError('invalid JSON constant')
    decoder=json.JSONDecoder(parse_constant=invalid_constant)
    root_keys={'verdict','conditions','questions','issues','passages','records'}
    def whitespace(p):
        while p<len(raw) and raw[p].isspace():p+=1
        return p
    def delimiter(p):
        while p<len(raw) and (raw[p].isspace() or raw[p] in '{}[],'):p+=1
        return p
    def pair(p):
        key,end=decoder.raw_decode(raw,p)
        if not isinstance(key,str):raise ValueError('non-string key')
        end=whitespace(end)
        if end>=len(raw) or raw[end]!=':':raise ValueError('missing colon')
        return key,whitespace(end+1)
    def collection(p):
        items={}
        while True:
            p=delimiter(p)
            if p>=len(raw):return items,p
            start=p;key,pair_end=pair(p)
            if key in root_keys:return items,start
            value,end=decoder.raw_decode(raw,pair_end)
            if key in items or not isinstance(value,dict):raise ValueError('ambiguous record')
            items[key]=value;p=end
    def scalars(text):
        found=[];p=0
        while p<len(text):
            if text[p].isspace() or text[p] in '{}[],:':p+=1;continue
            value,end=decoder.raw_decode(text,p)
            if type(value) not in (str,int,float,bool,type(None)):raise ValueError('not scalar')
            found.append((type(value).__name__,value));p=end
        return found
    try:
        result={};p=0
        while True:
            p=delimiter(p)
            if p>=len(raw):break
            key,p=pair(p)
            if key not in root_keys or key in result:raise ValueError('ambiguous root key')
            if key in {'conditions','questions','passages','records'}:value,p=collection(p)
            else:value,p=decoder.raw_decode(raw,p)
            result[key]=value
        (_EncodingFlatReview if 'records' in result else _EncodingPassageReview if 'passages' in result else KeyedReview).model_validate(result)
        if scalars(raw)!=scalars(json.dumps(result,ensure_ascii=False,allow_nan=False)):
            raise ValueError('not lossless')
        return result
    except (ValueError,TypeError):return None
