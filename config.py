from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(exist_ok=True)

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_BASE_URL = (os.getenv("OPENAI_BASE_URL") or "").strip().rstrip("/")
CHAT_MODEL = (os.getenv("CHAT_MODEL") or "").strip()
IMAGE_MODEL = (os.getenv("IMAGE_MODEL") or "").strip()
I2V_MODEL = (os.getenv("I2V_MODEL") or "").strip()

STICKER_COUNT = int(os.getenv("STICKER_COUNT") or "8")
VIDEO_CONCURRENCY = int(os.getenv("VIDEO_CONCURRENCY") or "3")
VIDEO_DURATION = int(os.getenv("VIDEO_DURATION") or "5")
VIDEO_SIZE = (os.getenv("VIDEO_SIZE") or "").strip()

HOST = os.getenv("HOST") or "127.0.0.1"
PORT = int(os.getenv("PORT") or "8765")

DEFAULT_CHARACTER = (
    "Q版大头小身可爱角色，粗黑描边、扁平色块上色、表情夸张。纯白背景，贴纸构图，主体居中。"
    "角色形象必须在整套表情包中保持完全一致。"
)


def i2v_enabled() -> bool:
    return bool(I2V_MODEL)


def missing_required() -> list[str]:
    missing: list[str] = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not OPENAI_BASE_URL:
        missing.append("OPENAI_BASE_URL")
    if not CHAT_MODEL:
        missing.append("CHAT_MODEL")
    if not IMAGE_MODEL:
        missing.append("IMAGE_MODEL")
    return missing
