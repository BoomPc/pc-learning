import copy
import json
import pytest
from math_agent.pipeline import Runner
from math_agent.storage import write_json
from math_agent.rendering import RenderError


class MemoryCache:
    data = None
    def __init__(self, *args): self.data = None
    def get(self, key): return self.data
    def put(self, key, value): self.data = value


def provider(queue, stages):
    class Fake:
        def __init__(self, settings, audit): self.calls = 0
        def generate(self, stage, *args, **kwargs):
            stages.append(stage); self.calls += 1
            return copy.deepcopy(queue.pop(0))
        def close(self): pass
    return Fake


def renderer(spec, directory, validate_only=False):
    directory.mkdir(exist_ok=True)
    if not validate_only:
        (directory / "result.html").write_text("offline fixture")
        write_json(directory / "export-check.json", {"status":"pass","engine":"fixture","sample_count":0,"samples":[]})


def test_math_objection_returns_to_solver(settings, job, sample):
    source, candidate, review = sample
    objection = copy.deepcopy(review); objection.update(verdict="revise", issues=[{"stage": "math", "target": "Q2", "detail": "遗漏边界"}])
    objection["questions"][1]["verdict"] = "issue"
    stages = []
    runner = Runner(settings, job[1], provider([source, candidate, objection, {"solutions":candidate["solutions"]}, review], stages), MemoryCache, renderer)
    runner.run()
    assert stages == ["source", "solve", "review", "math_repair", "review"]
    assert job[0].get(job[1])["status"] == "completed"


def test_source_objection_reextracts(settings, job, sample):
    source, candidate, review = sample
    objection = copy.deepcopy(review); objection.update(verdict="revise", issues=[{"stage": "source", "target": "C1", "detail": "读题需重新核对"}])
    stages = []
    Runner(settings, job[1], provider([source, candidate, objection, source, candidate, review], stages), MemoryCache, renderer).run()
    assert stages == ["source", "solve", "review", "source", "solve", "review"]


def test_ambiguous_source_stops_before_solver(settings, job, sample):
    source = sample[0]; source["uncertainties"] = ["B 点名称不清晰"]
    stages = []
    Runner(settings, job[1], provider([source], stages), MemoryCache, renderer).run()
    assert stages == ["source"]
    assert job[0].get(job[1])["status"] == "needs_input"


def test_diagram_repair_cannot_change_solution(settings, job, sample):
    source, candidate, review = sample
    objection = copy.deepcopy(review); objection.update(verdict="revise", issues=[{"stage": "diagram", "target": "P", "detail": "P 坐标不对"}])
    changed = copy.deepcopy(candidate); changed["solutions"][0]["result"] = "偷偷改了数学答案"
    stages = []
    Runner(settings, job[1], provider([source, candidate, objection, __import__("test_objection_gate").resolution(objection,candidate), changed], stages), MemoryCache, renderer).run()
    row = job[0].get(job[1])
    assert row["status"] == "failed" and "改写数学" in row["error"]
    assert stages[-1] == "diagram"


def test_cached_job_never_calls_model_even_when_render_fails(settings, job, sample):
    stages = []
    runner = Runner(settings, job[1], provider(list(sample), stages), MemoryCache, renderer)
    runner.run()
    cached = runner.cache.data
    assert cached
    store, _, _ = job
    new_id, path = store.prepare()
    write_json(path / "request.json", {"text": "离线测试题", "images": [], "force": False})
    store.enqueue(new_id); store.claim()
    new = Runner(settings, new_id, provider([], stages), MemoryCache, renderer)
    new.cache.data = cached
    new.run()
    assert store.get(new_id)["summary"]["model_calls_this_job"] == 0
    assert len(stages) == 3

    def fail(*args, **kwargs): raise RenderError("新版引擎不接受该图")
    failed_id, path = store.prepare()
    write_json(path / "request.json", {"text": "离线测试题", "images": [], "force": False})
    store.enqueue(failed_id); store.claim()
    failed = Runner(settings, failed_id, provider([], stages), MemoryCache, fail); failed.cache.data = cached; failed.run()
    assert store.get(failed_id)["status"] == "failed" and len(stages) == 3


def test_force_bypasses_cache(settings, job, sample):
    request = json.loads((job[2] / "request.json").read_text()); request["force"] = True
    write_json(job[2] / "request.json", request)
    stages = []
    runner = Runner(settings, job[1], provider(list(sample), stages), MemoryCache, renderer)
    runner.cache.get = lambda _: pytest.fail("forced job must not read cache")
    runner.run()
    assert stages == ["source", "solve", "review"]


def test_renderer_failure_is_reviewed_after_repair(settings, job, sample):
    stages = []; source, candidate, review = sample; failures = []
    def unstable(spec, directory, validate_only=False):
        if not validate_only and not failures: failures.append(1); raise RenderError("浏览器交互错误")
        return renderer(spec, directory, validate_only)
    Runner(settings, job[1], provider([source, candidate, candidate, review], stages), MemoryCache, unstable).run()
    assert stages == ["source", "solve", "diagram", "review"]
    assert job[0].get(job[1])["status"] == "completed"


def test_pass_with_objection_is_downgraded_to_repair_never_published(settings,job,sample):
    source,candidate,review=sample
    inconsistent=copy.deepcopy(review)
    inconsistent['issues']=[{'stage':'diagram','target':'A','detail':'图形需要核对'}]
    stages=[]
    Runner(settings,job[1],provider([source,candidate,inconsistent,__import__('test_objection_gate').resolution({**inconsistent,'verdict':'revise'},candidate),candidate,review],stages),MemoryCache,renderer).run()
    assert stages==['source','solve','review','adjudicate','diagram','review']
    assert job[0].get(job[1])['status']=='completed'


def test_displayed_question_uses_authoritative_source(settings,sample):
    from math_agent.pipeline import canonical_page
    from math_agent.contracts import Source,Candidate,check_candidate
    source=Source.model_validate(sample[0]);candidate=Candidate.model_validate(sample[1])
    candidate.spec['problem_text']='模型重复题干时遗漏了一个条件'
    canonical_page(candidate,source)
    assert candidate.spec['problem_text']==source.problem_text
    check_candidate(candidate,source)


def test_invalid_condition_reference_gets_bounded_correction(settings,job,sample):
    source,candidate,review=sample
    bad=copy.deepcopy(candidate);bad['solutions'][0]['condition_ids'].append('Q1')
    stages=[]
    Runner(settings,job[1],provider([source,bad,candidate,review],stages),MemoryCache,renderer).run()
    assert stages==['source','solve','solve','review']
    assert job[0].get(job[1])['status']=='completed'


def test_repeated_invalid_output_stops(settings,job,sample):
    source,candidate,_=sample
    bad=copy.deepcopy(candidate);bad['solutions'][0]['condition_ids']=['unknown']
    stages=[]
    Runner(settings,job[1],provider([source,bad,bad],stages),MemoryCache,renderer).run()
    assert stages==['source','solve','solve']
    assert job[0].get(job[1])['status']=='failed'


def test_source_format_correction_preserves_ambiguity(settings,job,sample):
    source=copy.deepcopy(sample[0]);source['uncertainties']=['点名看不清']
    bad=copy.deepcopy(source);bad['unexpected']=True
    stages=[]
    Runner(settings,job[1],provider([bad,source],stages),MemoryCache,renderer).run()
    assert stages==['source','source']
    assert job[0].get(job[1])['status']=='needs_input'


def test_network_failure_is_not_format_retry(settings,job,sample):
    from math_agent.provider import ModelError
    stages=[]
    class Failed:
        calls=0
        def __init__(self,*args): pass
        def generate(self,stage,*args,**kwargs):
            self.calls+=1;stages.append(stage)
            raise ModelError('网络失败，不重发')
        def close(self): pass
    Runner(settings,job[1],Failed,MemoryCache,renderer).run()
    assert stages==['source']
    assert job[0].get(job[1])['status']=='failed'


def test_review_missing_checks_is_corrected_before_publish(settings,job,sample):
    source,candidate,review=sample
    bad=copy.deepcopy(review);bad['questions']=[]
    stages=[]
    Runner(settings,job[1],provider([source,candidate,bad,review],stages),MemoryCache,renderer).run()
    assert stages==['source','solve','review','review']
    assert job[0].get(job[1])['status']=='completed'


def test_explicit_resume_only_reviews_completed_candidate(settings,job,sample):
    from dataclasses import replace
    source,candidate,review=sample
    stages=[]
    initial=Runner(settings,job[1],provider(list(sample),stages),MemoryCache,renderer)
    initial.run()
    report=json.loads((job[2]/'report.json').read_text())
    report.update(status='failed',error='达到模型调用预算上限；测试',model_calls_this_job=10)
    write_json(job[2]/'report.json',report)
    with job[0].connection() as c:c.execute("UPDATE jobs SET status='failed' WHERE id=?",(job[1],))
    resumed=[]
    runner=Runner(replace(settings,max_calls=14),job[1],provider([review],resumed),MemoryCache,renderer)
    runner.resume_review()
    assert resumed==['review']
    assert job[0].get(job[1])['status']=='completed'
    assert runner.provider.calls==11
    assert (job[2]/'report-before-resume-10.json').is_file()


def test_resume_rejects_other_failures(settings,job,sample):
    write_json(job[2]/'report.json',{'status':'failed','error':'网络错误'})
    job[0].finish(job[1],'failed',error='网络错误')
    stages=[]
    runner=Runner(settings,job[1],provider([],stages),MemoryCache,renderer)
    with pytest.raises(ValueError,match='预算耗尽'):runner.resume_review()
    assert stages==[]
