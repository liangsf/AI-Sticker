from __future__ import annotations

import json
import re
import sys
import threading

from flask import Flask, jsonify, request, send_from_directory

from config import DEFAULT_CHARACTER, HOST, OUTPUTS, PORT, STICKER_COUNT, i2v_enabled, missing_required
from pipeline import new_job_id, run_pipeline

app = Flask(__name__, static_folder="static", static_url_path="/static")

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
_JOB_ID_RE = re.compile(r"^[\w-]+$")


def _set_job(job_id: str, **fields) -> None:
    with jobs_lock:
        job = jobs.setdefault(
            job_id,
            {"id": job_id, "status": "queued", "logs": [], "manifest": None, "error": None},
        )
        job.update(fields)


def _append_log(job_id: str, stage: str, extra: dict | None) -> None:
    with jobs_lock:
        job = jobs[job_id]
        entry = {"stage": stage, **(extra or {})}
        job["logs"].append(entry)
        job["status"] = "running" if stage != "done" else "done"
        if stage == "done" and extra and extra.get("manifest"):
            job["manifest"] = extra["manifest"]
        if stage == "error":
            job["status"] = "error"
            job["error"] = (extra or {}).get("message")


def _start_worker(job_id: str, theme: str, character: str, resume: bool = False) -> None:
    def worker():
        try:
            def progress(stage: str, extra: dict | None):
                _append_log(job_id, stage, extra)

            manifest = run_pipeline(theme, character, job_id, progress=progress, resume=resume)
            _set_job(job_id, status="done", manifest=manifest)
        except Exception as exc:  # noqa: BLE001
            _append_log(job_id, "error", {"message": str(exc)})

    threading.Thread(target=worker, daemon=True).start()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    missing = missing_required()
    return jsonify(
        {
            "ok": not missing,
            "missing": missing,
            "i2v_enabled": i2v_enabled(),
        }
    )


@app.get("/api/defaults")
def defaults():
    return jsonify(
        {
            "character": DEFAULT_CHARACTER,
            "count": STICKER_COUNT,
            "i2v_enabled": i2v_enabled(),
        }
    )


@app.post("/api/generate")
def generate():
    data = request.get_json(force=True, silent=True) or {}
    theme = (data.get("theme") or "").strip()
    character = (data.get("character") or "").strip()
    if not theme:
        return jsonify({"error": "请输入主题"}), 400

    job_id = new_job_id()
    _set_job(job_id, status="queued", theme=theme, character=character or DEFAULT_CHARACTER)
    _start_worker(job_id, theme, character, resume=False)
    return jsonify({"job_id": job_id})


@app.post("/api/resume/<job_id>")
def resume(job_id: str):
    if not _JOB_ID_RE.match(job_id):
        return jsonify({"error": "无效的任务 ID"}), 400

    work = OUTPUTS / job_id
    plan_path = work / "plan.json"
    if not plan_path.exists():
        return jsonify({"error": f"任务不存在或缺少 plan.json: {job_id}"}), 404

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    theme = (plan.get("theme") or "").strip()
    character = (plan.get("character") or DEFAULT_CHARACTER).strip()

    with jobs_lock:
        existing = jobs.get(job_id)
        if existing and existing.get("status") == "running":
            return jsonify({"error": "该任务正在运行中"}), 409

    _set_job(
        job_id,
        status="queued",
        theme=theme,
        character=character,
        logs=[],
        error=None,
        manifest=None,
    )
    _start_worker(job_id, theme, character, resume=True)
    return jsonify({"job_id": job_id, "resumed": True})


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    if not _JOB_ID_RE.match(job_id):
        return jsonify({"error": "无效的任务 ID"}), 400

    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            manifest_path = OUTPUTS / job_id / "manifest.json"
            plan_path = OUTPUTS / job_id / "plan.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                return jsonify({"id": job_id, "status": "done", "logs": [], "manifest": manifest, "error": None})
            if plan_path.exists():
                return jsonify(
                    {
                        "id": job_id,
                        "status": "paused",
                        "logs": [],
                        "manifest": None,
                        "error": None,
                        "message": "有未完成进度，可调用续跑",
                    }
                )
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(job)


@app.get("/outputs/<job_id>/<path:filename>")
def serve_output(job_id: str, filename: str):
    if not _JOB_ID_RE.match(job_id):
        return jsonify({"error": "无效的任务 ID"}), 400
    folder = OUTPUTS / job_id
    return send_from_directory(folder, filename)


def main() -> None:
    missing = missing_required()
    if missing:
        print("缺少必要配置：" + ", ".join(missing))
        print("请复制 .env.example 为 .env，填写 API Key、兼容接口地址和模型名后再启动。")
        sys.exit(1)
    mode = "静图 + 动图" if i2v_enabled() else "仅静图（未配置 I2V_MODEL）"
    print(f"模式：{mode}")
    print(f"打开 http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
