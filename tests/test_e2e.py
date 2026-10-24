"""Real API/storage/worker/HTTP/tool/browser path; only the model replies are fixtures."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from PIL import Image
from math_agent.api import create_app
from math_agent.config import Settings
from math_agent.storage import Store
from math_agent.worker import supervise


@contextmanager
def private_redis():
    executable = shutil.which("redis-server")
    if not executable: pytest.skip("完整缓存集成测试需要 redis-server")
    with tempfile.TemporaryDirectory(prefix="math-agent-redis-", dir="/tmp") as temporary:
        socket = str(Path(temporary) / "redis.sock")
        process = subprocess.Popen([executable, "--port", "0", "--unixsocket", socket, "--save", "", "--appendonly", "no"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import redis
            client = redis.Redis(unix_socket_path=socket)
            for _ in range(100):
                try:
                    if client.ping(): break
                except redis.RedisError: pass
                time.sleep(.05)
            else: raise RuntimeError("临时 Redis 启动失败")
            yield "unix://" + socket
        finally:
            process.terminate(); process.wait(timeout=5)


@pytest.mark.skipif(os.getenv("MATH_AGENT_BROWSER_TEST") != "1", reason="需要显式启用真实浏览器集成测试")
def test_full_job_with_mock_model_and_real_tool_and_browser(tmp_path, monkeypatch, sample):
    with private_redis() as redis_url:
        run_job_case(tmp_path, monkeypatch, sample, redis_url)


def run_job_case(tmp_path, monkeypatch, sample, redis_url):
    source, candidate, review = sample
    responses = [
        {"role": "assistant", "content": json.dumps(source, ensure_ascii=False)},
        {"role": "assistant", "content": None, "reasoning_content": "test-only reasoning",
            "tool_calls": [{"id": "calc1", "type": "function", "function": {"name": "algebra_batch", "arguments": json.dumps({"operations": [{"op": "solve", "variables": ["x"], "equations": ["x**2-2*x=0"]}]})}}]},
        {"role": "assistant", "content": json.dumps(candidate, ensure_ascii=False)},
        {"role": "assistant", "content": json.dumps(review, ensure_ascii=False)},
    ]
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            message = responses.pop(0)
            body = json.dumps({"model": "offline-fixture", "choices": [{"message": message, "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}], "usage": {"total_tokens": 10}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        for name, value in {"AGENT_DATA_DIR": str(tmp_path), "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            "DEEPSEEK_API_KEY": "offline-fixture-key", "AGENT_ACCESS_TOKEN": "x"*40, "REDIS_URL": redis_url}.items(): monkeypatch.setenv(name, value)
        settings = Settings(); client = create_app(settings).test_client(); auth = {"Authorization": "Bearer " + settings.access_token}
        picture = io.BytesIO(); Image.new("RGB", (300, 100), "white").save(picture, "PNG"); raw_picture = picture.getvalue(); picture.seek(0)
        submission = client.post("/api/jobs", headers=auth, data={"text": source["problem_text"], "question": (picture, "fixture.png")})
        assert submission.status_code == 202
        job_id = submission.json["id"]; store = Store(tmp_path); assert store.claim() == job_id
        supervise(settings, store, job_id, lambda: False, lambda: None)
        row = client.get(f"/api/jobs/{job_id}", headers=auth).json
        assert row["status"] == "completed", row
        assert len(requests) == 4
        assert any(part["type"] == "image_url" for part in requests[0]["messages"][1]["content"])
        assert requests[2]["messages"][-2]["reasoning_content"] == "test-only reasoning"
        report = client.get(f"/api/jobs/{job_id}/artifacts/report.json", headers=auth).json
        assert report["model_calls_this_job"] == 4
        assert any(e["kind"] == "tool" and e["result"]["ok"] for e in report["audit"])
        assert "test-only reasoning" not in json.dumps(report)
        result = client.get(f"/api/jobs/{job_id}/artifacts/result.html", headers=auth)
        assert result.status_code == 200 and "attachment" in result.headers["Content-Disposition"]
        assert "sandbox allow-scripts" in result.headers["Content-Security-Policy"]
        repeated = client.post("/api/jobs", headers=auth, data={"text": source["problem_text"], "question": (io.BytesIO(raw_picture), "same-fixture.png")})
        second_id = repeated.json["id"]; assert store.claim() == second_id
        supervise(settings, store, second_id, lambda: False, lambda: None)
        second = store.get(second_id)
        assert second["status"] == "completed", second
        assert second["summary"]["cache_hit"] and second["summary"]["model_calls_this_job"] == 0
        assert len(requests) == 4
        print(json.dumps({"test": "mock_model_real_worker_redis_browser", "first_seconds": report["seconds"], "cached_seconds": second["summary"]["seconds"], "model_http_calls": len(requests), "real_tool_calls": sum(e["kind"] == "tool" for e in report["audit"])}))
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=os.getenv("GGB_CHROMIUM_EXECUTABLE"))
            page = browser.new_page(); page.goto((store.path(job_id) / "output/result.html").as_uri())
            page.locator(".tab-btn").nth(1).click()
            slider = page.locator("input[type=range]")
            slider.evaluate("s => {s.value=0.5;s.dispatchEvent(new Event('input',{bubbles:true}));}")
            before = page.locator(".answer-panel.active svg").first.inner_html()
            slider.evaluate("s => {s.value=1.5;s.dispatchEvent(new Event('input',{bubbles:true}));}")
            after = page.locator(".answer-panel.active svg").first.inner_html()
            assert before != after and "NaN" not in after and "Infinity" not in after
            page.locator(".answer-panel.active .jump-btn").first.click()
            assert float(slider.input_value()) == 1
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            # Exercise the actual online workbench and protected inline preview over HTTP.
            from werkzeug.serving import make_server
            http = make_server("127.0.0.1", 0, create_app(settings), threaded=True)
            web_thread = threading.Thread(target=http.serve_forever, daemon=True); web_thread.start()
            try:
                web = browser.new_page()
                web.goto(f"http://127.0.0.1:{http.server_port}/")
                web.locator("#token").fill(settings.access_token)
                web.locator("#job").fill(job_id); web.locator("#recover").click()
                web.locator("#preview").wait_for(state="visible")
                frame = web.frame_locator("#preview")
                frame.locator("html[data-ready=true]").wait_for()
                assert frame.locator(".tab-btn").count() == 2
                frame.locator(".tab-btn").nth(1).click()
                frame.locator(".jump-btn").first.click()
                assert float(frame.locator("input[type=range]").input_value()) == 1
                assert web.locator("#preview").get_attribute("sandbox") == "allow-scripts"
                assert client.get(f"/api/jobs/{job_id}/preview").status_code == 401
                preview = client.get(f"/api/jobs/{job_id}/preview", headers=auth)
                assert preview.status_code == 200 and "inline" in preview.headers["Content-Disposition"]
                assert report["render_check"]["engine"] == "JSXGraph"
                web.close()
            finally:
                http.shutdown(); http.server_close(); web_thread.join(timeout=3)
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
