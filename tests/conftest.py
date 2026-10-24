import copy
import json
from pathlib import Path
import pytest
from math_agent.config import Settings, ROOT
from math_agent.storage import Store, write_json


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, api_key="fake-offline-key", access_token="a"*40, redis_url="", max_calls=12)


@pytest.fixture
def sample():
    spec = json.loads((ROOT / "examples/demo-spec.json").read_text())
    source = {"title": spec["title"], "problem_text": spec["problem_text"],
        "conditions": [{"id": "C1", "text": "y=-x²+2x", "origin": "question_text", "image_ids": []}],
        "questions": [{"id": "Q1", "text": "求交点"}, {"id": "Q2", "text": "求最大面积"}], "reference_summary": "", "uncertainties": []}
    candidate = {"solutions": [{"question_id": "Q"+str(i), "result": tab["conclusion"],
        "steps": [{"premise": "根据题设", "rule": step["head"], "conclusion": step["content"]} for step in tab["steps"]],
        "cases": [], "domain_and_boundaries": "0≤t≤2，端点退化", "condition_ids": ["C1"]} for i, tab in enumerate(spec["tabs"], 1)], "spec": spec}
    review = {"verdict": "pass", "conditions": [{"id": "C1", "verdict": "pass", "evidence": "原题抛物线与转写一致"}],
        "questions": [{"id": "Q1", "verdict": "pass", "evidence": "因式分解得到两交点"}, {"id": "Q2", "verdict": "pass", "evidence": "面积配方，极值及端点均核验"}], "issues": []}
    return source, candidate, review


@pytest.fixture
def job(settings):
    store = Store(settings.data_dir)
    job_id, directory = store.prepare()
    write_json(directory / "request.json", {"text": "离线测试题", "images": [], "force": False})
    write_json(directory / "image-roles.json", {})
    store.enqueue(job_id); store.claim()
    return store, job_id, directory
