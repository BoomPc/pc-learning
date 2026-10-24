"""Explicit operator-requested diagram revision of a completed job.

A new queued job retains provenance and original mathematics. No automatic paid retry.
"""
import json
import shutil
from .storage import Store, write_json
from .contracts import Source, Candidate, Issue, check_source, check_candidate


def validate_revision(data, request):
    source=Source.model_validate(data['source']);candidate=Candidate.model_validate(data['candidate'])
    check_source(source,request['images']);check_candidate(candidate,source)
    if source.uncertainties: raise ValueError('未决题意不能进入单独构图修订')
    feedback=[Issue.model_validate(f) for f in data['feedback']]
    if not 1<=len(feedback)<=10 or any(f.stage!='diagram' for f in feedback):
        raise ValueError('此入口只接受明确的构图修订；数学异议必须重新解题')
    return source,candidate,[f.model_dump() for f in feedback]


def create_diagram_revision(settings, original_id, feedback):
    store=Store(settings.data_dir);original=store.path(original_id);row=store.get(original_id)
    if not row or row['status']!='completed': raise ValueError('只可显式修订已完成任务')
    request=json.loads((original/'request.json').read_text());request['force']=True
    data={'original_id':original_id,'source':json.loads((original/'source.json').read_text()),
          'candidate':json.loads((original/'candidate.json').read_text()),'feedback':feedback}
    validate_revision(data,request)
    job,path=store.prepare()
    for img in request['images']:
        source=(original/img['file']).resolve()
        if not source.is_relative_to(original.resolve()): raise ValueError('原图路径不合法')
        destination=path/img['file'];destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination);destination.chmod(0o600)
    write_json(path/'request.json',request)
    write_json(path/'revision.json',data)
    store.enqueue(job)
    return job
