from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent
APP_CONFIG_PATH = ROOT / "config.json"

DEFAULT_ZHIBO8_CONFIG: dict[str, Any] = {
    "saishi_id": "",
    "match_date": "",
    "match_url": "",
    "league_id": "4",
    "poll_intervals": {
        "livetext": 2,
        "animate": 2,
        "lineup": 60,
        "score": 10,
        "report": 30,
    },
}

def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    merged = deepcopy(default)
    merged.update(data)
    return merged       

def load_zhibo8_config() -> dict[str, Any]:
    app_config = load_json(APP_CONFIG_PATH, {})
    zhibo8 = deepcopy(DEFAULT_ZHIBO8_CONFIG)
    zhibo8.update(app_config.get("zhibo8") or {})
    return zhibo8


def save_zhibo8_config(data: dict[str, Any]) -> None:
    app_config = load_json(APP_CONFIG_PATH, {})
    app_config["zhibo8"] = data
    save_json(APP_CONFIG_PATH, app_config)
