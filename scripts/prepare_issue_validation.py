"""Freeze a saved mathematical objection for a later explicitly approved run.

This command is offline only: it never creates a model client, runs a job,
imports a previous pass, edits a proof or submits anything to production.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from math_agent.contracts import Source,Candidate,Issue,check_source,check_candidate
from math_agent.pipeline import canonical_page
from math_agent.math_review_scope import engine_binding
from math_agent.review_reuse import digest
from math_agent.storage import write_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('验收文件路径越界')
    return path


def prepare(origin,candidate_file,feedback_file,out):
    origin=Path(origin).resolve();candidate_file=Path(candidate_file).resolve();feedback_file=Path(feedback_file).resolve()
    out=Path(out).resolve()
    if out.exists():raise ValueError('验收包已存在，不覆盖旧证据')
    source=Source.model_validate_json((feedback_file.parent/'source.json').read_text())
    candidate=Candidate.model_validate_json(candidate_file.read_text())
    associated=Candidate.model_validate_json((feedback_file.parent/'candidate.json').read_text())
    if candidate!=associated:raise ValueError('异议不属于所选候选版本')
    feedback=json.loads(feedback_file.read_text())
    if feedback.get('status')!='revise' or feedback.get('accepted') is not False:raise ValueError('需要明确未通过且带数学异议的原核对记录，不能导入或编造pass')
    issues=[Issue.model_validate(x) for x in feedback['issues']]
    if not issues or any(i.stage!='math' for i in issues):raise ValueError('此单轮入口仅接受现存数学异议')
    old_request=json.loads((origin/'request.json').read_text());images=[];copies=[]
    for index,img in enumerate(old_request['images']):
        path=checked_path(origin,img['file'])
        if sha(path)!=img['sha256']:raise ValueError('原图内容与原任务哈希不一致')
        suffix=path.suffix.lower()
        if suffix not in {'.png','.jpg','.jpeg','.webp'}:raise ValueError('图片类型不受支持')
        name=f'images/image-{index:02d}'+suffix
        images.append({**{k:img[k] for k in ('id','role','sha256')},'file':name});copies.append((path,name))
    request={'text':old_request['text'],'images':images,'force':True}
    check_source(source,images);check_candidate(candidate,source)
    if canonical_page(candidate.model_copy(deep=True),source)!=candidate:raise ValueError('候选展示文本与证明版本不一致')
    out.mkdir(parents=True,mode=0o700);(out/'images').mkdir(mode=0o700)
    for path,name in copies:
        shutil.copyfile(path,out/name);(out/name).chmod(0o600)
    for name,value in [('source.json',source.model_dump()),('candidate.json',candidate.model_dump()),
                       ('feedback.json',[i.model_dump() for i in issues]),('request.json',request)]:write_json(out/name,value)
    files=['source.json','candidate.json','feedback.json','request.json']+[i['file'] for i in images]
    body={'status':'prepared_only','paid_calls':0,'end_to_end':False,'engine_sha256':engine_binding(),
        'files':{name:sha(out/name) for name in files},
        'origin':str(origin),'original_feedback_sha256':sha(feedback_file),
        'plan':{'stages':['math_repair','observe','full_review','deferred_if_required'],
                'max_calls':6,'job_timeout_seconds':240,'effort':'low','max_tokens':64000,
                'import_previous_review':False,'reuse_old_question_passes':False,
                'automatic_job_retries':0,'source_solve_ocr_calls':0,
                'publication':'none; diagnostic requires separate human teaching acceptance'}}
    manifest={**body,'sha256':digest(body)};write_json(out/'manifest.json',manifest)
    verify(out)
    return manifest


def verify(out):
    out=Path(out).resolve();manifest=json.loads((out/'manifest.json').read_text())
    if digest({k:v for k,v in manifest.items() if k!='sha256'})!=manifest['sha256']:raise ValueError('验收包清单摘要不符')
    if manifest['engine_sha256']!=engine_binding():raise ValueError('代码版本已变化，须重新离线预检；未自动执行模型')
    for name,expected in manifest['files'].items():
        if sha(checked_path(out,name))!=expected:raise ValueError('验收输入内容已变化：'+name)
    request=json.loads((out/'request.json').read_text())
    expected={'source.json','candidate.json','feedback.json','request.json'}|{i['file'] for i in request['images']}
    if set(manifest['files'])!=expected:raise ValueError('验收包没有完整覆盖输入文件')
    for img in request['images']:
        if sha(checked_path(out,img['file']))!=img['sha256']:raise ValueError('冻结原图哈希不一致')
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--verify',type=Path)
    ap.add_argument('--origin',type=Path);ap.add_argument('--candidate',type=Path)
    ap.add_argument('--feedback',type=Path);ap.add_argument('--out',type=Path)
    a=ap.parse_args()
    if a.verify:result=verify(a.verify)
    else:
        if not all((a.origin,a.candidate,a.feedback,a.out)):ap.error('准备需要origin/candidate/feedback/out；不会执行付费请求')
        result=prepare(a.origin,a.candidate,a.feedback,a.out)
    print(json.dumps({'status':result['status'],'sha256':result['sha256'],'paid_calls':0,
                      'note':'离线预检成功；没有运行数学修订、模型复核或发布。'},ensure_ascii=False))


if __name__=='__main__':main()
