"""微信表情包生成管线：主题规划 → 静图 →（可选）图生视频 → GIF → 配套素材。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from client import chat_json, generate_image, image_to_video
from config import (
    DEFAULT_CHARACTER,
    OUTPUTS,
    ROOT,
    STICKER_COUNT,
    VIDEO_CONCURRENCY,
    i2v_enabled,
)

ProgressFn = Callable[[str, dict[str, Any] | None], None]


def _emit(progress: ProgressFn | None, stage: str, **extra: Any) -> None:
    if progress:
        progress(stage, extra or None)


def plan_stickers(theme: str, character: str) -> dict[str, Any]:
    system = (
        "你是微信表情包策划。根据主题设计一整套表情包。"
        "只输出合法 JSON，不要 markdown 代码块。"
    )
    user = f"""主题：{theme}
角色设定：{character or DEFAULT_CHARACTER}

请规划恰好 {STICKER_COUNT} 张表情，输出 JSON：
{{
  "pack_name": "专辑中文名（2-8字）",
  "character_prompt": "英文为主的固定角色描述，贯穿全部静图，含 chibi / bold outline / flat colors / pure white background",
  "stickers": [
    {{
      "id": "01_xxx",
      "label": "中文情绪名",
      "caption": "短文案（1-4字，可出现在图上）",
      "scene": "中文场景说明",
      "image_prompt": "英文静图提示词：角色描述 + 情绪动作 + caption text bubble + white background sticker",
      "motion_prompt": "英文图生视频动作提示（短、循环感）"
    }}
  ]
}}

要求：
1. stickers 必须正好 {STICKER_COUNT} 条，id 形如 01_hi、02_happy
2. 情绪/场景贴合主题，覆盖打招呼、开心、生气、委屈、无语、加油等日常聊天用途
3. character_prompt 固定，各 image_prompt 必须复用同一角色描述，只改情绪与动作
4. caption 简洁有梗，适合聊天发送
"""
    text = chat_json(system, user)
    data = _parse_json(text)
    stickers = data.get("stickers") or []
    if len(stickers) != STICKER_COUNT:
        raise RuntimeError(f"规划结果不是 {STICKER_COUNT} 张，实际 {len(stickers)}")
    data["character_prompt"] = data.get("character_prompt") or character or DEFAULT_CHARACTER
    return data


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise
        return json.loads(match.group(0))


def mp4_to_gif(mp4: Path, gif: Path) -> None:
    script = ROOT / "mp4_to_gif.py"
    subprocess.run(
        ["python3", str(script), str(mp4), str(gif)],
        check=True,
        cwd=str(ROOT),
    )


def make_icon(src: Path, dst: Path) -> None:
    script = ROOT / "make_icon.py"
    subprocess.run(
        ["python3", str(script), str(src), str(dst)],
        check=True,
        cwd=str(ROOT),
    )


def _center_crop_resize(src: Path, dst: Path, tw: int, th: int, jpeg: bool = False) -> None:
    img = Image.open(src).convert("RGB")
    sw, sh = img.size
    target_ratio = tw / th
    ratio = sw / sh
    if ratio > target_ratio:
        nw = int(sh * target_ratio)
        left = (sw - nw) // 2
        img = img.crop((left, 0, left + nw, sh))
    else:
        nh = int(sw / target_ratio)
        top = (sh - nh) // 2
        img = img.crop((0, top, sw, top + nh))
    img = img.resize((tw, th), Image.LANCZOS)
    if jpeg:
        img.save(dst, format="JPEG", quality=90, optimize=True)
    else:
        img.save(dst, format="PNG", optimize=True)


def generate_extras(work: Path, character_prompt: str, pack_name: str, progress: ProgressFn | None) -> None:
    _emit(progress, "extras", message="生成横幅/封面/图标…")

    banner_prompt = (
        f"{character_prompt}. Warm colorful story scene for WeChat sticker pack banner, "
        f"no text, no watermark, rich background, characters interacting, theme: {pack_name}."
    )
    banner_raw = work / "_banner_raw.png"
    generate_image(banner_prompt, banner_raw, size="2048x1152")
    _center_crop_resize(banner_raw, work / "横幅_详情页_750x400.jpg", 750, 400, jpeg=True)

    cover_prompt = (
        f"{character_prompt}. Square album cover composition different from banner, "
        "no text, soft colorful background, cute sticker style."
    )
    cover_raw = work / "_cover_raw.png"
    generate_image(cover_prompt, cover_raw, size="1024x1024")
    _center_crop_resize(cover_raw, work / "封面_240x240.png", 240, 240)

    icon_prompt = (
        f"{character_prompt}. Close-up of character head only, front view, fill the frame, "
        "solid pure green background (#00FF00), no text, no border."
    )
    icon_raw = work / "_icon_raw.png"
    generate_image(icon_prompt, icon_raw, size="1024x1024")
    make_icon(icon_raw, work / "聊天页图标_50x50.png")


def _package_manifest(
    work: Path,
    job_id: str,
    theme: str,
    character: str,
    pack_name: str,
    ordered: list[dict[str, Any]],
) -> dict[str, Any]:
    zip_path = work / f"{pack_name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in ordered:
            for key in ("gif", "image"):
                name = item.get(key)
                if not name:
                    continue
                path = work / name
                if path.exists():
                    zf.write(path, arcname=name)
        for name in ("横幅_详情页_750x400.jpg", "封面_240x240.png", "聊天页图标_50x50.png", "plan.json"):
            path = work / name
            if path.exists():
                zf.write(path, arcname=name)

    manifest = {
        "job_id": job_id,
        "theme": theme,
        "pack_name": pack_name,
        "character": character or DEFAULT_CHARACTER,
        "i2v_enabled": i2v_enabled(),
        "stickers": ordered,
        "zip": zip_path.name,
        "files": {
            "banner": "横幅_详情页_750x400.jpg",
            "cover": "封面_240x240.png",
            "icon": "聊天页图标_50x50.png",
        },
    }
    (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _generate_stills(
    work: Path,
    stickers: list[dict[str, Any]],
    character_prompt: str,
    progress: ProgressFn | None,
) -> None:
    _emit(progress, "images", message="开始生成静态表情图…", total=len(stickers), done=0)
    for i, item in enumerate(stickers, start=1):
        sid = item["id"]
        png = work / f"{sid}.png"
        if png.exists() and png.stat().st_size > 0:
            _emit(
                progress,
                "image",
                message=f"跳过已有静图 {i}/{len(stickers)}: {item.get('label')}",
                done=i,
                total=len(stickers),
                id=sid,
            )
            continue
        prompt = item.get("image_prompt") or (
            f"{character_prompt}. Emotion: {item.get('label')}. "
            f"Action: {item.get('scene')}. Caption bubble: {item.get('caption')}."
        )
        _emit(
            progress,
            "image",
            message=f"生图 {i}/{len(stickers)}: {item.get('label')}",
            done=i,
            total=len(stickers),
            id=sid,
        )
        generate_image(prompt, png)


def _generate_videos(
    work: Path,
    stickers: list[dict[str, Any]],
    progress: ProgressFn | None,
) -> list[dict[str, Any]]:
    _emit(progress, "videos", message=f"开始图生视频（并发最多 {VIDEO_CONCURRENCY}）…", total=len(stickers), done=0)
    done_videos = 0
    lock = threading.Lock()

    def _one_video(item: dict[str, Any]) -> dict[str, Any]:
        nonlocal done_videos
        sid = item["id"]
        png = work / f"{sid}.png"
        mp4 = work / f"{sid}.mp4"
        gif = work / f"{sid}.gif"
        if gif.exists() and gif.stat().st_size > 0:
            with lock:
                done_videos += 1
                _emit(
                    progress,
                    "video",
                    message=f"跳过已有动图 {done_videos}/{len(stickers)}: {item.get('label')}",
                    done=done_videos,
                    total=len(stickers),
                    id=sid,
                    gif=gif.name,
                )
            return {**item, "gif": gif.name, "image": png.name, "mp4": mp4.name if mp4.exists() else None, "status": "gif_ready"}

        if not png.exists():
            raise RuntimeError(f"缺少静图，无法图生视频: {png.name}")

        motion = item.get("motion_prompt") or f"subtle looping sticker animation for {item.get('label')}"
        if not (mp4.exists() and mp4.stat().st_size > 0):
            image_to_video(png, motion, mp4)
        mp4_to_gif(mp4, gif)
        with lock:
            done_videos += 1
            _emit(
                progress,
                "video",
                message=f"动图完成 {done_videos}/{len(stickers)}: {item.get('label')}",
                done=done_videos,
                total=len(stickers),
                id=sid,
                gif=gif.name,
            )
        return {**item, "gif": gif.name, "image": png.name, "mp4": mp4.name, "status": "gif_ready"}

    with ThreadPoolExecutor(max_workers=VIDEO_CONCURRENCY) as pool:
        futures = [pool.submit(_one_video, item) for item in stickers]
        video_results = [fut.result() for fut in as_completed(futures)]

    by_id = {r["id"]: r for r in video_results}
    return [by_id[s["id"]] for s in stickers]


def _static_results(work: Path, stickers: list[dict[str, Any]], progress: ProgressFn | None) -> list[dict[str, Any]]:
    _emit(progress, "videos", message="未配置 I2V_MODEL，跳过动图，使用静图交付")
    ordered = []
    for item in stickers:
        sid = item["id"]
        png = work / f"{sid}.png"
        if not png.exists():
            raise RuntimeError(f"缺少静图: {png.name}")
        ordered.append({**item, "image": png.name, "gif": None, "status": "image_ready"})
    return ordered


def run_pipeline(
    theme: str,
    character: str,
    job_id: str,
    progress: ProgressFn | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    work = OUTPUTS / job_id
    if resume:
        if not work.exists() or not (work / "plan.json").exists():
            raise RuntimeError(f"无法续跑：找不到任务目录或 plan.json ({job_id})")
        _emit(progress, "resume", message=f"从已有进度续跑：{job_id}")
        plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
        theme = theme or plan.get("theme") or ""
    else:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        _emit(progress, "plan", message=f"正在根据主题规划 {STICKER_COUNT} 张表情…")
        plan = plan_stickers(theme, character)
        plan["theme"] = theme
        plan["character"] = character or DEFAULT_CHARACTER
        (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    pack_name = plan.get("pack_name") or (theme[:8] if theme else job_id)
    character_prompt = plan["character_prompt"]
    stickers = plan["stickers"]
    character = character or plan.get("character") or DEFAULT_CHARACTER

    _generate_stills(work, stickers, character_prompt, progress)

    if i2v_enabled():
        ordered = _generate_videos(work, stickers, progress)
    else:
        ordered = _static_results(work, stickers, progress)

    banner = work / "横幅_详情页_750x400.jpg"
    cover = work / "封面_240x240.png"
    icon = work / "聊天页图标_50x50.png"
    if banner.exists() and cover.exists() and icon.exists():
        _emit(progress, "extras", message="跳过已有配套素材")
    else:
        generate_extras(work, character_prompt, pack_name, progress)

    manifest = _package_manifest(work, job_id, theme, character, pack_name, ordered)
    _emit(progress, "done", message="全部完成", manifest=manifest)
    return manifest


def new_job_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
