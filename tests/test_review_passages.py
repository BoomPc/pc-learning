import copy
import pytest
from jsonschema import validate,ValidationError
from math_agent.contracts import Source,Candidate
from math_agent.compact_review import output_schema
from math_agent.review_passages import passages,normalize
from test_compact_review import pack_review


def flat_review(raw):
    return {'verdict':raw['verdict'],'records':{**copy.deepcopy(raw['conditions']),**copy.deepcopy(raw['questions']),
        **copy.deepcopy(raw['passages'])},'issues':copy.deepcopy(raw['issues'])}


def inputs(sample):
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    candidate.solutions[1].cases=['端点须单独核对，不允许省略分类讨论']
    expected=passages(candidate,['Q1','Q2']);raw=pack_review(sample[2])
    raw['passages']={p['id']:{'quote':p['text'],'verdict':'pass','evidence':'已逐字核对原句与推导'} for p in expected}
    return source,candidate,expected,raw


def test_literal_coverage_is_bound_to_all_original_case_and_boundary_paragraphs(sample):
    source,candidate,expected,raw=inputs(sample)
    ids=[p['id'] for p in expected]
    assert {'Q1:result','Q1:domain','Q2:result','Q2:domain','Q2:case:1'}<=set(ids)
    assert len(ids)==5+sum(len(s.steps) for s in candidate.solutions)
    first=next(p for p in expected if p['id']=='Q1:step:1')
    step=candidate.solutions[0].steps[0]
    assert first['text']==step.premise+'\n'+step.rule+'\n'+step.conclusion
    before=copy.deepcopy(raw)
    assert normalize(raw,expected)=={k:v for k,v in raw.items() if k!='passages'}
    assert raw==before
    schema=output_schema(source.model_dump(),expected)
    validate(raw,schema)
    wrong=copy.deepcopy(raw);wrong['passages']['Q2:domain']['quote']='改成正确原文后试图蒙混通过'
    with pytest.raises(ValidationError):validate(wrong,schema)
    with pytest.raises(ValueError):normalize(wrong,expected)


@pytest.mark.parametrize('bad',['missing','extra','no_passages'])
def test_missing_or_unknown_literal_records_cannot_publish(sample,bad):
    _,_,expected,raw=inputs(sample)
    if bad=='missing':raw['passages'].pop('Q2:case:1')
    elif bad=='extra':raw['passages']['Q9:domain']=copy.deepcopy(raw['passages']['Q1:domain'])
    else:raw.pop('passages')
    with pytest.raises(ValueError):normalize(raw,expected)


@pytest.mark.parametrize('verdict',['issue','unknown'])
def test_explicit_literal_disagreement_or_unknown_cannot_hide_under_root_pass(sample,verdict):
    _,_,expected,raw=inputs(sample)
    raw['passages']['Q2:domain'].update(verdict=verdict,evidence='原句端点的取等对象与代回原式的结果不同，须更正原文')
    original={'stage':'source','target':'C1','detail':'另一个真实题设异议必须保留'}
    raw['issues'].append(original)
    result=normalize(raw,expected)
    assert result['verdict']==('revise' if verdict=='issue' else 'needs_input')
    assert result['questions']['Q2']['verdict']==verdict
    assert original in result['issues']
    if verdict=='issue':assert any(i['stage']=='math' and i['target']=='Q2:domain' for i in result['issues'])


def test_only_omitted_constant_quote_metadata_may_be_bound_without_changing_model_judgments(sample):
    _,_,expected,raw=inputs(sample);before=copy.deepcopy(raw);audit=[]
    raw['passages']['Q2:domain'].pop('quote')
    original=copy.deepcopy(raw)
    result=normalize(raw,expected,audit=lambda k,v:audit.append((k,v)))
    assert result=={k:v for k,v in before.items() if k!='passages'}
    assert raw==original and audit[0][1]['passage_ids']==['Q2:domain']
    # Verdicts, evidence, paragraph IDs and existing strings are not constants
    # the runtime may invent, correct, delete or replace.
    for field in ['verdict','evidence']:
        invalid=copy.deepcopy(raw);invalid['passages']['Q2:domain'].pop(field)
        with pytest.raises(ValueError):normalize(invalid,expected)


def test_lossless_syntax_recovery_does_not_invent_missing_constant_metadata(sample):
    import json
    from math_agent.compact_review import repair_encoding
    _,_,expected,raw=inputs(sample)
    raw['passages']['Q2:domain'].pop('quote')
    malformed=json.dumps(raw,ensure_ascii=False).replace('"conditions": {','"conditions": {{',1)
    recovered=repair_encoding(malformed)
    assert recovered==raw and 'quote' not in recovered['passages']['Q2:domain']
    assert normalize(recovered,expected)=={k:v for k,v in raw.items() if k!='passages'}


def test_single_map_preserves_each_judgment_issue_and_quote_without_group_ambiguity(sample):
    from math_agent.review_passages import decode_flat
    source,_,expected,raw=inputs(sample);flat=flat_review(raw);before=copy.deepcopy(flat)
    flat['records']['C1']['quote']='模型附加的原题引文保留在原始核验表中，不改题设'
    decoded=decode_flat(flat,source,expected)
    assert normalize(decoded,expected)=={k:v for k,v in raw.items() if k!='passages'}
    assert flat['records']['C1']['quote']=='模型附加的原题引文保留在原始核验表中，不改题设'
    schema=output_schema(source.model_dump(),expected,flat=True)
    assert set(schema['properties'])=={'verdict','records','issues'}
    assert set(schema['properties']['records']['required'])==set(before['records'])
    for invalid in [{}, {**flat,'questions':{}}, {**flat,'records':{k:v for k,v in flat['records'].items() if k!='Q2'}}]:
        with pytest.raises(ValueError):decode_flat(invalid,source,expected)
    import json
    from math_agent.compact_review import repair_encoding
    malformed=json.dumps(flat,ensure_ascii=False).replace('"records": {','"records": {{',1)
    assert repair_encoding(malformed)==flat
