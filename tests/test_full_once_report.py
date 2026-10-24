import json
import pytest
from math_agent.pipeline import Runner
from scripts.evaluate_full_once import execute_and_read_report
from test_pipeline import MemoryCache, provider, renderer


def test_evaluator_reads_real_runner_completion(settings, job, sample):
    stages=[]
    runner=Runner(settings,job[1],provider(list(sample),stages),MemoryCache,renderer)
    result=execute_and_read_report(runner,job[2])
    assert result['status']=='completed'
    assert stages==['source','solve','review']
    assert job[0].get(job[1])['status']=='completed'


def test_execution_failure_cannot_be_hidden_by_saved_report(settings, job, sample):
    (job[2]/'report.json').write_text(json.dumps({'status':'completed'}))
    def fail(*args,**kwargs):
        raise RuntimeError('render failed')
    runner=Runner(settings,job[1],provider(list(sample),[]),MemoryCache,fail)
    with pytest.raises(RuntimeError,match='render failed'):
        execute_and_read_report(runner,job[2])
