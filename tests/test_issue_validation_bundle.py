import json
from pathlib import Path
import pytest
from scripts.prepare_issue_validation import prepare,verify
from math_agent.contracts import Source,Candidate
from math_agent.pipeline import canonical_page
from math_agent.storage import write_json


def files(sample,tmp_path):
    origin=tmp_path/'origin';origin.mkdir();review=tmp_path/'human';review.mkdir()
    s=Source.model_validate(sample[0]);c=canonical_page(Candidate.model_validate(sample[1]),s)
    write_json(origin/'request.json',{'text':'独立验收夹具','images':[],'force':False})
    write_json(review/'source.json',s.model_dump());write_json(review/'candidate.json',c.model_dump())
    write_json(review/'human-review.json',{'status':'revise','accepted':False,'issues':[
        {'stage':'math','target':'Q1','detail':'保留真实原异议，不能将数值核对或默认图正常当作证明。'}]})
    return origin,review


def test_offline_bundle_never_creates_model_client_or_invents_previous_pass(sample,tmp_path,monkeypatch):
    origin,review=files(sample,tmp_path)
    monkeypatch.setattr('math_agent.provider.DeepSeek.__init__',lambda *a,**kw:pytest.fail('离线预检不能创建模型客户端'))
    out=tmp_path/'bundle';m=prepare(origin,review/'candidate.json',review/'human-review.json',out)
    assert verify(out)==m and m['paid_calls']==0 and not m['end_to_end']
    assert m['plan']['max_calls']==6 and m['plan']['job_timeout_seconds']==240
    assert not m['plan']['import_previous_review'] and not (out/'review.json').exists()
    assert json.loads((out/'feedback.json').read_text())[0]['target']=='Q1'
    with pytest.raises(ValueError,match='不覆盖'):prepare(origin,review/'candidate.json',review/'human-review.json',out)


def test_unrelated_candidate_cannot_borrow_another_versions_objection(sample,tmp_path):
    origin,review=files(sample,tmp_path);c=json.loads((review/'candidate.json').read_text());c['solutions'][0]['result']='另一个版本'
    other=tmp_path/'other.json';write_json(other,c)
    with pytest.raises(ValueError,match='不属于'):prepare(origin,other,review/'human-review.json',tmp_path/'bundle')


@pytest.mark.parametrize('mode',['candidate','code','outside'])
def test_changed_input_or_engine_cannot_be_silently_used_for_later_paid_request(sample,tmp_path,monkeypatch,mode):
    origin,review=files(sample,tmp_path);out=tmp_path/'bundle';prepare(origin,review/'candidate.json',review/'human-review.json',out)
    if mode=='candidate':(out/'candidate.json').write_text('{}')
    elif mode=='code':monkeypatch.setattr('scripts.prepare_issue_validation.engine_binding',lambda:'new-code')
    else:
        from scripts.prepare_issue_validation import checked_path
        with pytest.raises(ValueError,match='越界'):checked_path(out,'../outside')
        return
    with pytest.raises(ValueError):verify(out)


def test_an_accepted_or_nonmathematical_review_cannot_be_used_as_repair_seed(sample,tmp_path):
    origin,review=files(sample,tmp_path);path=review/'human-review.json';raw=json.loads(path.read_text());raw['accepted']=True;write_json(path,raw)
    with pytest.raises(ValueError,match='未通过'):prepare(origin,review/'candidate.json',path,tmp_path/'bundle')


@pytest.mark.parametrize('stale_original',[False,True])
def test_original_and_frozen_images_are_checked_by_actual_bytes_before_execution(sample,tmp_path,stale_original):
    import hashlib
    origin,review=files(sample,tmp_path)
    image=origin/'I1.png';image.write_bytes(b'original-image-bytes')
    write_json(origin/'request.json',{'text':'离线图片哈希夹具','force':False,'images':[
        {'id':'I1','role':'question','file':'I1.png','sha256':hashlib.sha256(image.read_bytes()).hexdigest()}]})
    out=tmp_path/'bundle'
    if stale_original:
        image.write_bytes(b'changed-original')
        with pytest.raises(ValueError,match='原图内容'):prepare(origin,review/'candidate.json',review/'human-review.json',out)
        assert not out.exists()
    else:
        m=prepare(origin,review/'candidate.json',review/'human-review.json',out)
        request=json.loads((out/'request.json').read_text());frozen=out/request['images'][0]['file']
        assert frozen.read_bytes()==image.read_bytes() and verify(out)==m
        frozen.write_bytes(b'changed-bundle-image')
        with pytest.raises(ValueError,match='内容已变化'):verify(out)
