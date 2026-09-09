"""共用工具：設定檔、路徑、日期、重試。"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ANALYSIS_DIR = ROOT / "analysis"
REPORTS_DIR = ROOT / "reports"
FIXTURES_DIR = ROOT / "fixtures"

log = logging.getLogger("fetch")


def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def now_tw(cfg: Optional[dict] = None) -> datetime:
    tz = (cfg or {}).get("timezone", "Asia/Taipei")
    return datetime.now(ZoneInfo(tz))


def report_key(session: str, date: Optional[datetime] = None, cfg: Optional[dict] = None) -> str:
    """報告識別字串，例如 2026-09-09-am。"""
    d = date or now_tw(cfg)
    return f"{d.strftime('%Y-%m-%d')}-{session}"


def data_path(key: str) -> Path:
    return DATA_DIR / f"{key}.json"


def analysis_path(key: str) -> Path:
    return ANALYSIS_DIR / f"{key}.json"


def report_path(key: str, cfg: Optional[dict] = None) -> Path:
    out = (cfg or {}).get("report", {}).get("output_dir", "reports")
    return ROOT / out / f"{key}.html"


def retry(fn: Callable[[], Any], tries: int = 3, wait: float = 2.0, label: str = "") -> Any:
    last: Optional[BaseException] = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            log.warning("%s 失敗 (%d/%d): %s", label or fn.__name__, i + 1, tries, e)
            time.sleep(wait * (i + 1))
    raise RuntimeError(f"{label} 重試 {tries} 次仍失敗: {last}")


def pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """(a/b - 1) * 100，任一為 None 或 b==0 回傳 None。"""
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1) * 100, 2)


def rnd(x: Any, n: int = 2) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return round(v, n)
    except (TypeError, ValueError):
        return None


def dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def roc_date(d: datetime) -> str:
    """民國日期 113/09/09 格式（TPEX 舊 API 用）。"""
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


def previous_weekday(d: datetime, n: int = 1) -> datetime:
    while n > 0:
        d = d - timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d
