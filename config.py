from __future__ import annotations

import os
from pathlib import Path
from typing import List


def _load_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _load_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


TELEGRAM_SESSION_NAME: str = "newsbot"
TELEGRAM_API_ID: int = _load_int("TELEGRAM_API_ID", 0)
TELEGRAM_API_HASH: str = _load_str("TELEGRAM_API_HASH", "replace_me")
TELEGRAM_BOT_TOKEN: str = _load_str("TELEGRAM_BOT_TOKEN", "replace_me")

TELEGRAM_CHANNELS: List[str] = [
    "@technomedia",
    "@yaroslavl_smi",
    "@novosti_efir",
    "@neural_braining",
    "@naebnet",
    "@techmedia",
    "@kharchevnikov",
    "@trendswhat",
    "@chatgptv",
]

TELEGRAM_FETCH_LIMIT: int = 30
DATABASE_PATH: Path = Path("data/posts.db")
SEARCH_RESULT_LIMIT: int = 5
