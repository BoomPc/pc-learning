from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import sys
import time
from .config import Settings, ROOT


def parent_guard():
    if os.getpgrp() != os.getpid():
        raise RuntimeError("run-job 只能由 Worker 在独立进程组启动")
    if sys.platform == "linux":
        import ctypes
        # The child owns its process group. A hard worker crash kills its entire job tree.
        parent = os.getppid()
        def orphan(*_): os.killpg(os.getpgrp(), signal.SIGKILL)
        signal.signal(signal.SIGTERM, orphan)
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
        if parent == 1 or os.getppid() != parent: orphan()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Linux 初中数学 Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve"); serve.add_argument("--host", default="127.0.0.1"); serve.add_argument("--port", type=int, default=8000)
    worker = sub.add_parser("worker"); worker.add_argument("--once", action="store_true")
    job = sub.add_parser("run-job"); job.add_argument("id")
    sub.add_parser("doctor")
    submit = sub.add_parser("submit")
    submit.add_argument("--url", default="http://127.0.0.1:8000")
    submit.add_argument("--question", action="append", default=[])
    submit.add_argument("--answer", action="append", default=[])
    submit.add_argument("--text", default="")
    submit.add_argument("--force", action="store_true")
    submit.add_argument("--output", type=Path, default=Path("downloads"))
    args = parser.parse_args()
    settings = Settings()
    if args.command == "serve":
        from waitress import serve
        from .api import create_app
        from .image_input import MAX_REQUEST
        serve(create_app(settings), host=args.host, port=args.port, threads=4, max_request_body_size=MAX_REQUEST)
    elif args.command == "worker":
        from .worker import run_worker
        run_worker(settings, args.once)
    elif args.command == "run-job":
        parent_guard()
        from .pipeline import Runner
        Runner(settings, args.id).run()
    elif args.command == "doctor":
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            executable = Path(os.getenv("MATH_AGENT_CHROMIUM_EXECUTABLE") or os.getenv("GGB_CHROMIUM_EXECUTABLE", p.chromium.executable_path))
            browser_ok = executable.is_file()
            if browser_ok:
                browser = p.chromium.launch(headless=True, executable_path=str(executable)); browser.close()
        from .ocr import healthy
        report = {"ocr_ready": healthy(settings), "ocr_enabled": bool(settings.ocr_url), "python": sys.version.split()[0], "model": settings.model, "key_configured": bool(settings.api_key),
            "service_token_configured": len(settings.access_token) >= 32, "chromium_launch_ok": browser_ok,
            "engine_present": (ROOT / "math_agent/jsxgraph/vendor/jsxgraphcore.js").is_file(),
            "redis_configured": bool(settings.redis_url), "live_model_tested": False}
        if settings.redis_url:
            import redis
            try: report["redis_connected"] = bool(redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping())
            except Exception: report["redis_connected"] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ocr_ready"] or not browser_ok or not report["engine_present"] or report.get("redis_connected") is False: raise SystemExit(1)
    elif args.command == "submit":
        import httpx
        from urllib.parse import urlparse
        target = urlparse(args.url)
        if target.scheme != "https" and not (target.scheme == "http" and target.hostname in {"localhost", "127.0.0.1"}):
            parser.error("远程服务请使用 HTTPS；HTTP 只用于本机或 SSH 转发")
        with ExitStack() as stack, httpx.Client(headers={"Authorization": "Bearer " + settings.access_token}, timeout=60) as client:
            files = [(role, (Path(path).name, stack.enter_context(open(path, "rb")))) for role, paths in [("question", args.question), ("answer", args.answer)] for path in paths]
            response = client.post(args.url.rstrip("/")+"/api/jobs", files=files or None, data={"text": args.text, "force": str(args.force).lower()})
            if response.status_code != 202: print(response.text[:2000]); raise SystemExit(1)
            job_id = response.json()["id"]
            print("任务：" + job_id, flush=True)
            last = None
            deadline = time.monotonic() + 7200
            while time.monotonic() < deadline:
                response = client.get(args.url.rstrip("/")+"/api/jobs/"+job_id); response.raise_for_status(); row = response.json()
                if row["stage"] != last: print(row["stage"], flush=True); last = row["stage"]
                if row["status"] in {"completed", "failed", "needs_input", "cancelled", "interrupted"}: break
                time.sleep(2)
            else: print("客户端等待结束，任务仍在服务端；使用任务编号继续查询"); raise SystemExit(1)
            if row["status"] != "completed": print(row.get("error") or row["status"]); raise SystemExit(1)
            directory = args.output / job_id; directory.mkdir(parents=True, exist_ok=True)
            for name, url in row["artifacts"].items():
                response = client.get(args.url.rstrip("/")+url); response.raise_for_status(); (directory/name).write_bytes(response.content)
            print(str((directory / "result.html").resolve()))


if __name__ == "__main__": main()
