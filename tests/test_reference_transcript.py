import copy
import pytest
from math_agent.reference_transcript import check_transcript
from math_agent.contracts import Source


def test_transcript_requires_every_question_and_answer_image_provenance(sample):
    source=Source.model_validate(sample[0]);before=source.model_dump()
    images=[{'id':'A','role':'answer'},{'id':'Q','role':'question'}]
    raw={'sections':[{'question_id':q.id,'lines':[{'image_id':'A','text':'参考声称：未必正确'}],'unreadable':[]} for q in source.questions]}
    assert check_transcript(raw,source,images).sections[0].lines[0].text=='参考声称：未必正确'
    assert source.model_dump()==before
    for change in ('missing','duplicate','question_image','unknown_image','empty'):
        bad=copy.deepcopy(raw)
        if change=='missing':bad['sections'].pop()
        if change=='duplicate':bad['sections'].append(bad['sections'][0])
        if change=='question_image':bad['sections'][0]['lines'][0]['image_id']='Q'
        if change=='unknown_image':bad['sections'][0]['lines'][0]['image_id']='invented'
        if change=='empty':bad['sections'][0]['lines']=[]
        with pytest.raises(ValueError):check_transcript(bad,source,images)
    raw['sections'][0].update(lines=[],unreadable=['公式看不清'])
    assert check_transcript(raw,source,images).sections[0].unreadable


def test_unreadable_reference_stops_before_math_without_changing_source(sample,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from math_agent import reference_transcript as module
    from math_agent.pipeline import NeedsInput
    source=Source.model_validate(sample[0]);before=source.model_dump()
    raw={'sections':[{'question_id':q.id,'lines':[],'unreadable':['看不清']} for q in source.questions]}
    runner=object.__new__(module.TranscriptRunner)
    runner.directory=tmp_path;runner.request={'images':[{'id':'A','role':'answer'}]}
    runner.provider=SimpleNamespace(generate=lambda *a,**k:raw)
    runner.audit=lambda *a:None
    monkeypatch.setattr(module,'messages',lambda *a:[])
    def unexpected(*a,**k):raise AssertionError('不得继续解题')
    monkeypatch.setattr(module.OutlineRunner,'validated',unexpected)
    with pytest.raises(NeedsInput):runner.validated('reference_math',{'source':source.model_dump()},lambda raw:raw)
    assert source.model_dump()==before
    assert (tmp_path/'reference-transcript.json').exists()
