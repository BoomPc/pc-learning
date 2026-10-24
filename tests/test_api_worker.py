from dataclasses import replace
import io
import json
import signal
import sys
from PIL import Image
from math_agent.api import create_app
from math_agent.storage import Store
from math_agent.worker import supervise


def png(color):
    buffer = io.BytesIO(); Image.new("RGB", (20, 30), color).save(buffer, "PNG"); buffer.seek(0)
    return buffer


def test_auth_upload_roles_and_artifact_block(settings):
    client = create_app(settings).test_client(); auth = {"Authorization": "Bearer " + settings.access_token}
    assert client.get("/healthz").status_code == 200
    assert client.post("/api/jobs", data={"text": "x"}).status_code == 401
    result = client.post("/api/jobs", headers=auth, data={"question": (png("white"), "../../q.jpg"), "answer": (png("gray"), "a.png")})
    assert result.status_code == 202
    job_id = result.json["id"]; directory = Store(settings.data_dir).path(job_id)
    request = json.loads((directory / "request.json").read_text())
    assert [x["role"] for x in request["images"]] == ["question", "answer"]
    assert [x["file"] for x in request["images"]] == ["input-01.png", "input-02.png"]
    assert client.get(f"/api/jobs/{job_id}/artifacts/request.json", headers=auth).status_code == 404
    assert client.get(f"/api/jobs/{job_id}/artifacts/result.html", headers=auth).status_code == 404
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=auth).json["status"] == "cancelled"
    assert Store(settings.data_dir).claim() is None


def test_missing_key_and_bad_uploads(settings):
    auth = {"Authorization": "Bearer " + settings.access_token}
    assert create_app(replace(settings, api_key="")).test_client().post("/api/jobs", headers=auth, data={"text": "题目"}).status_code == 503
    client = create_app(settings).test_client()
    assert client.post("/api/jobs", headers=auth, data={"answer": (png("white"), "a.png")}).status_code == 400
    assert client.post("/api/jobs", headers=auth, data={"question": (io.BytesIO(b"not image"), "q.png")}).status_code == 400
    assert not list((settings.data_dir / "jobs").iterdir())


def test_cancel_cannot_be_overwritten_by_finish(settings, job):
    store, job_id, _ = job
    store.finish(job_id, "cancelled"); store.finish(job_id, "completed")
    assert store.get(job_id)["status"] == "cancelled"


def test_recovery_does_not_requeue_paid_jobs(settings, job):
    job[0].recover()
    assert job[0].get(job[1])["status"] == "interrupted"
    assert job[0].claim() is None


def test_worker_stop_terminates_process(settings, job):
    store, job_id, _ = job
    supervise(settings, store, job_id, lambda: True, lambda: None,
        command=[sys.executable, "-c", "import time; time.sleep(60)"])
    assert store.get(job_id)["status"] == "interrupted"


def test_worker_total_timeout(settings, job):
    # Patch only runtime setting in a test; public settings enforce >=30 seconds.
    object.__setattr__(settings, "job_timeout", .1)
    supervise(settings, job[0], job[1], lambda: False, lambda: None,
        command=[sys.executable, "-c", "import time; time.sleep(60)"])
    assert job[0].get(job[1])["status"] == "failed"
    assert "总时限" in job[0].get(job[1])["error"]
