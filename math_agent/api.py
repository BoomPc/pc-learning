from __future__ import annotations
import hmac
import json
from pathlib import Path
import shutil
import time
from flask import Flask, jsonify, request, send_file
from .image_input import save_image, MAX_REQUEST
from .storage import Store, TERMINAL, write_json
from .config import ROOT

def create_app(settings):
    if len(settings.access_token) < 32:
        raise ValueError("请先设置至少32字符的 AGENT_ACCESS_TOKEN，与 DeepSeek Key 分开")
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=MAX_REQUEST, MAX_FORM_MEMORY_SIZE=128*1024)
    store = Store(settings.data_dir)

    @app.before_request
    def authorize():
        if request.path not in {"/healthz", "/"} and not hmac.compare_digest(request.headers.get("Authorization", "").encode("utf-8"), ("Bearer " + settings.access_token).encode("utf-8")):
            return jsonify(error="需要有效的服务访问令牌"), 401

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Rendered HTML is delivered as an attachment; don't give it same-origin privileges.
        if response.mimetype == "text/html" and request.path != "/":
            response.headers["Content-Security-Policy"] = "sandbox allow-scripts; default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline' 'unsafe-eval'; font-src data:"
        if request.path == "/":
            response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-src 'self' about:; form-action 'none'; base-uri 'none'"
        return response

    @app.errorhandler(413)
    def too_large(_): return jsonify(error="上传总大小不能超过200 MiB"), 413

    @app.get("/")
    def workbench():
        return send_file(ROOT / "math_agent/web/workbench.html")

    @app.get("/healthz")
    def health(): return jsonify(status="alive")

    @app.get("/readyz")
    def ready():
        heartbeat = settings.data_dir / "worker-heartbeat.json"
        try: worker = time.time() - json.loads(heartbeat.read_text())["at"] < 10
        except (OSError, ValueError, KeyError): worker = False
        from .ocr import healthy
        ocr_ready = healthy(settings)
        configured = bool(settings.api_key)
        return jsonify(ready=configured and worker and ocr_ready, ocr_ready=ocr_ready, key_configured=configured, worker_alive=worker, model=settings.model), (200 if configured and worker and ocr_ready else 503)

    @app.post("/api/jobs")
    def submit():
        if not settings.api_key: return jsonify(error="尚未配置 DEEPSEEK_API_KEY；当前不接受会调用模型的任务"), 503
        if set(request.files) - {"question", "answer"} or set(request.form) - {"text", "force"}:
            return jsonify(error="只支持 question/answer 文件和 text/force 字段"), 400
        text = request.form.get("text", "").strip()
        if len(text) > 20000: return jsonify(error="文字超过20000字"), 400
        if request.form.get("force", "false") not in {"true", "false"}: return jsonify(error="force 必须是 true 或 false"), 400
        questions, answers = request.files.getlist("question"), request.files.getlist("answer")
        if not text and not questions: return jsonify(error="至少需要题目文字或题图；答案图不能代替题目"), 400
        if len(questions) + len(answers) > 6: return jsonify(error="一次最多6张题图和答案图"), 400
        job_id, directory = store.prepare()
        try:
            images = []
            for index, (role, upload) in enumerate([("question", x) for x in questions] + [("answer", x) for x in answers], 1):
                filename = f"input-{index:02d}.png"
                sha = save_image(upload, directory / filename)
                images.append({"id": f"I{index}", "role": role, "file": filename, "sha256": sha})
            write_json(directory / "request.json", {"text": text, "images": images, "force": request.form.get("force") == "true"})
            write_json(directory / "image-roles.json", {i["file"]: i["role"] for i in images})
            store.enqueue(job_id)
        except ValueError as exc:
            shutil.rmtree(directory)
            return jsonify(error=str(exc)), 400
        except Exception:
            shutil.rmtree(directory)
            raise
        return jsonify(id=job_id, status="queued", status_url=f"/api/jobs/{job_id}"), 202

    def lookup(job_id):
        try: return store.get(job_id)
        except ValueError: return None

    @app.get("/api/jobs/<job_id>")
    def status(job_id):
        row = lookup(job_id)
        if not row: return jsonify(error="任务不存在"), 404
        if row["status"] == "completed": row["artifacts"] = {name: f"/api/jobs/{job_id}/artifacts/{name}" for name in ["result.html", "preview.png", "report.json"]}
        if row["status"] == "completed": row["preview_url"] = f"/api/jobs/{job_id}/preview"
        if row["status"] in TERMINAL and (store.path(job_id) / "ocr.json").is_file():
            row["ocr_url"] = f"/api/jobs/{job_id}/artifacts/ocr.json"
        return jsonify(row)

    @app.get("/api/jobs/<job_id>/preview")
    def preview(job_id):
        row = lookup(job_id)
        if not row or row["status"] != "completed": return jsonify(error="预览尚不可用"), 404
        path = store.path(job_id) / "output/result.html"
        if not path.is_file(): return jsonify(error="预览文件不存在"), 404
        return send_file(path, as_attachment=False, mimetype="text/html")

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel(job_id):
        row = lookup(job_id)
        if not row: return jsonify(error="任务不存在"), 404
        if row["status"] not in TERMINAL: store.finish(job_id, "cancelled", error="用户取消；已发出的模型请求可能仍会计费")
        return jsonify(store.get(job_id))

    @app.get("/api/jobs/<job_id>/artifacts/<name>")
    def artifact(job_id, name):
        row = lookup(job_id)
        if not row: return jsonify(error="任务不存在"), 404
        if name in {"report.json", "ocr.json", "evidence-ledger.json"}: path = store.path(job_id) / name
        elif name in {"result.html", "preview.png"} and row["status"] == "completed": path = store.path(job_id) / "output" / name
        else: return jsonify(error="该产物不可用"), 404
        if not path.is_file() or row["status"] not in TERMINAL: return jsonify(error="该产物尚未生成"), 404
        return send_file(path, as_attachment=True, download_name=name)

    return app
