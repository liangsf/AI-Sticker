"""OpenAI-compatible chat / image / image-to-video client."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from PIL import Image

from config import (
    CHAT_MODEL,
    I2V_MODEL,
    IMAGE_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    VIDEO_DURATION,
    VIDEO_SIZE,
)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            timeout=httpx.Timeout(30.0, read=300.0),
        )
    return _client


def chat_json(system: str, user: str, temperature: float = 0.7) -> str:
    reply = get_client().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return (reply.choices[0].message.content or "").strip()


def _normalize_size(size: str | None) -> str | None:
    if not size:
        return None
    return size.replace("*", "x").replace("×", "x")


def generate_image(prompt: str, out_path: Path, size: str = "1024x1024") -> None:
    """POST /images/generations，保存为本地 PNG。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wanted = _normalize_size(size)
    candidates = [wanted, "1024x1024", None]
    last_error: Exception | None = None
    seen: set[str | None] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            _generate_image_once(prompt, out_path, candidate)
            _flatten_white(out_path)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"文生图失败: {last_error}") from last_error


def _generate_image_once(prompt: str, out_path: Path, size: str | None) -> None:
    kwargs: dict[str, Any] = {"model": IMAGE_MODEL, "prompt": prompt, "n": 1}
    if size:
        kwargs["size"] = size
    response = get_client().images.generate(**kwargs)
    data = getattr(response, "data", None) or []
    if not data:
        raise RuntimeError(f"文生图未返回 data: {response}")
    item = data[0]
    b64 = getattr(item, "b64_json", None)
    url = getattr(item, "url", None)
    if b64:
        out_path.write_bytes(base64.b64decode(b64))
        return
    if url:
        _download(url, out_path)
        return
    raise RuntimeError(f"文生图结果既无 url 也无 b64_json: {item}")


def _flatten_white(path: Path) -> None:
    img = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    composed = Image.alpha_composite(bg, img).convert("RGB")
    composed.save(path, format="PNG")


def _download(url: str, path: Path) -> None:
    if not url or not str(url).startswith(("http://", "https://")):
        raise RuntimeError(f"无效下载地址: {url!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        path.write_bytes(response.content)


def _image_to_data_uri(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > 4_500_000:
        img = Image.open(path).convert("RGB")
        img.thumbnail((1024, 1024), Image.LANCZOS)
        from io import BytesIO

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=92)
        data = buf.getvalue()
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}"
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {OPENAI_API_KEY}"}


def _api_url(path: str) -> str:
    return f"{OPENAI_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def image_to_video(image_path: Path, prompt: str, out_mp4: Path) -> Path:
    """走 OpenAI Videos API：POST /videos + 轮询 + 下载。"""
    if not I2V_MODEL:
        raise RuntimeError("未配置 I2V_MODEL")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    try:
        _i2v_via_sdk(image_path, prompt, out_mp4)
        return out_mp4
    except Exception as exc:  # noqa: BLE001
        errors.append(f"SDK: {exc}")
    try:
        _i2v_via_http(image_path, prompt, out_mp4)
        return out_mp4
    except Exception as exc:  # noqa: BLE001
        errors.append(f"HTTP: {exc}")
    raise RuntimeError(
        "图生视频失败。请确认网关实现了 OpenAI Videos API（POST /videos），"
        f"或将 I2V_MODEL 留空只生成静图。详情: {' | '.join(errors)}"
    )


def _video_create_kwargs(prompt: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": I2V_MODEL, "prompt": prompt}
    if VIDEO_DURATION:
        kwargs["seconds"] = str(VIDEO_DURATION)
    if VIDEO_SIZE:
        kwargs["size"] = VIDEO_SIZE
    return kwargs


def _i2v_via_sdk(image_path: Path, prompt: str, out_mp4: Path) -> None:
    client = get_client()
    if not hasattr(client, "videos"):
        raise RuntimeError("当前 openai 库不支持 videos，请 pip install -U openai")

    def _create(with_media_params: bool) -> Any:
        extra = _video_create_kwargs(prompt) if with_media_params else {
            "model": I2V_MODEL,
            "prompt": prompt,
        }
        with image_path.open("rb") as handle:
            extra["input_reference"] = handle
            create = getattr(client.videos, "create_and_poll", None)
            if create:
                return create(poll_interval_ms=5000, **extra)
            video = client.videos.create(**extra)
            return _poll_video_sdk(client, video)

    try:
        video = _create(True)
    except TypeError:
        video = _create(False)

    status = getattr(video, "status", None)
    if status and status not in ("completed", "succeeded", "success"):
        error = getattr(video, "error", None) or getattr(video, "error_message", None)
        raise RuntimeError(f"图生视频未完成: status={status} error={error}")
    _save_video_result(client, video, out_mp4)


def _poll_video_sdk(client: OpenAI, video: Any, timeout: int = 1200) -> Any:
    deadline = time.time() + timeout
    while getattr(video, "status", None) in ("queued", "in_progress", "processing", "pending"):
        if time.time() > deadline:
            raise RuntimeError("图生视频超时")
        time.sleep(5)
        video = client.videos.retrieve(video.id)
    return video


def _save_video_result(client: OpenAI, video: Any, out_mp4: Path) -> None:
    url = getattr(video, "url", None) or getattr(video, "video_url", None)
    if url:
        _download(url, out_mp4)
        return
    download = getattr(client.videos, "download_content", None)
    if not download:
        raise RuntimeError("无法下载视频：无 url，且 SDK 无 download_content")
    content = download(video.id)
    if hasattr(content, "write_to_file"):
        content.write_to_file(str(out_mp4))
        return
    data = content.read() if hasattr(content, "read") else bytes(content)
    out_mp4.write_bytes(data)


def _i2v_via_http(image_path: Path, prompt: str, out_mp4: Path) -> None:
    """兼容只实现了 REST、SDK 字段略有差异的网关。"""
    payload = _video_create_kwargs(prompt)
    payload["input_reference"] = {"image_url": _image_to_data_uri(image_path)}
    with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as client:
        created = client.post(_api_url("videos"), headers={**_auth_headers(), "Content-Type": "application/json"}, json=payload)
        if created.status_code >= 400:
            created = client.post(
                _api_url("videos"),
                headers=_auth_headers(),
                files={
                    "input_reference": (image_path.name, image_path.read_bytes(), "image/png"),
                },
                data={k: str(v) for k, v in _video_create_kwargs(prompt).items()},
            )
        created.raise_for_status()
        body = created.json()
        video_id = body.get("id")
        if not video_id:
            url = body.get("url") or body.get("video_url") or ((body.get("data") or [{}])[0] or {}).get("url")
            if url:
                _download(url, out_mp4)
                return
            raise RuntimeError(f"图生视频未返回 id: {body}")

        deadline = time.time() + 1200
        while True:
            if time.time() > deadline:
                raise RuntimeError("图生视频超时")
            status_res = client.get(_api_url(f"videos/{video_id}"), headers=_auth_headers())
            status_res.raise_for_status()
            body = status_res.json()
            status = (body.get("status") or "").lower()
            if status in ("completed", "succeeded", "success"):
                url = body.get("url") or body.get("video_url")
                if url:
                    _download(url, out_mp4)
                    return
                content = client.get(_api_url(f"videos/{video_id}/content"), headers=_auth_headers())
                content.raise_for_status()
                out_mp4.write_bytes(content.content)
                return
            if status in ("failed", "error", "cancelled", "canceled"):
                raise RuntimeError(f"图生视频失败: {body}")
            time.sleep(5)
