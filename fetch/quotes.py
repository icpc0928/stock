"""透過 yfinance 抓歷史行情並計算常用指標（美股、台股個股、指數皆用同一套）。"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import pandas as pd

from .common import ROOT, pct, rnd

log = logging.getLogger("fetch.quotes")


def _rsi(close: pd.Series, n: int = 14) -> Optional[float]:
    if len(close) < n + 1:
        return None
    delta = close.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, float("nan"))
    rsi = 100 - 100 / (1 + rs)
    return rnd(rsi.iloc[-1], 1)


def summarize(df: pd.DataFrame, symbol: str, name: str = "") -> Optional[dict]:
    """把單一標的 OHLCV DataFrame 轉成報告用摘要 + 歷史序列。"""
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Close"])
    if df.empty:
        return None
    close = df["Close"]
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else None
    year_start = close[close.index.year == close.index[-1].year]
    ytd_base = float(year_start.iloc[0]) if len(year_start) > 1 else None
    hi52 = float(close.tail(252).max())
    lo52 = float(close.tail(252).min())
    ma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
    ma60 = float(close.tail(60).mean()) if len(close) >= 60 else None
    vol = df["Volume"] if "Volume" in df else None
    vol_last = float(vol.iloc[-1]) if vol is not None and len(vol) else None
    vol_avg20 = float(vol.tail(20).mean()) if vol is not None and len(vol) >= 5 else None

    hist = [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": rnd(row.get("Open")),
            "high": rnd(row.get("High")),
            "low": rnd(row.get("Low")),
            "close": rnd(row.get("Close")),
            "volume": rnd(row.get("Volume"), 0),
        }
        for idx, row in df.iterrows()
    ]
    return {
        "symbol": symbol,
        "name": name or symbol,
        "date": close.index[-1].strftime("%Y-%m-%d"),
        "last": rnd(last),
        "prev_close": rnd(prev),
        "change": rnd(last - prev) if prev is not None else None,
        "change_pct": pct(last, prev),
        "chg_5d_pct": pct(last, float(close.iloc[-6])) if len(close) > 6 else None,
        "chg_1m_pct": pct(last, float(close.iloc[-22])) if len(close) > 22 else None,
        "chg_ytd_pct": pct(last, ytd_base),
        "high_52w": rnd(hi52),
        "low_52w": rnd(lo52),
        "pos_52w_pct": rnd((last - lo52) / (hi52 - lo52) * 100, 1) if hi52 > lo52 else None,
        "ma20": rnd(ma20),
        "ma60": rnd(ma60),
        "vs_ma20_pct": pct(last, ma20),
        "vs_ma60_pct": pct(last, ma60),
        "rsi14": _rsi(close),
        "volume": rnd(vol_last, 0),
        "volume_ratio": rnd(vol_last / vol_avg20, 2) if vol_last and vol_avg20 else None,
        "history": hist,
    }


def fetch_many(symbols: List[str], names: Optional[Dict[str, str]] = None, days: int = 120,
               end: Optional[str] = None) -> Dict[str, dict]:
    """批次下載多檔，回傳 {symbol: summary}。end=YYYY-MM-DD 會切掉之後的資料（避免盤中未收盤的 K 棒混入）。"""
    import yfinance as yf  # 延後 import，讓 fixture 模式不需要安裝

    # yfinance 的時區快取預設放 ~/Library/Caches，在 launchd 下常常打不開 sqlite → 改放專案內
    try:
        cache = ROOT / ".cache" / "yfinance"
        cache.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache))
    except Exception as e:  # noqa: BLE001
        log.warning("設定 yfinance 快取位置失敗: %s", e)

    names = names or {}
    symbols = list(dict.fromkeys(s for s in symbols if s))
    if not symbols:
        return {}
    period = f"{max(days + 40, 60)}d"
    out: Dict[str, dict] = {}
    log.info("yfinance 下載 %d 檔 (%s)", len(symbols), period)
    def _download(syms):
        raw = yf.download(syms, period=period, interval="1d", group_by="ticker",
                          auto_adjust=False, threads=True, progress=False)
        for sym in syms:
            try:
                df = raw[sym] if len(syms) > 1 else raw
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(-1)
                if end:
                    df = df[df.index.strftime("%Y-%m-%d") <= end]
                s = summarize(df.tail(days), sym, names.get(sym, sym))
                if s:
                    out[sym] = s
            except Exception as e:  # noqa: BLE001
                log.debug("%s 解析失敗: %s", sym, e)

    _download(symbols)
    # 失敗的再補抓兩次（yfinance 批次下載偶爾會漏；網路閃斷也靠這裡救）
    for attempt in range(2):
        missing = [s for s in symbols if s not in out]
        if not missing:
            break
        log.warning("%d 檔無資料，%d 秒後重試: %s", len(missing), 3 * (attempt + 1), ",".join(missing[:12]))
        time.sleep(3 * (attempt + 1))
        _download(missing)
    missing = [s for s in symbols if s not in out]
    if missing:
        log.warning("最終仍無資料: %s", ",".join(missing))
    return out


def strip_history(d: dict, keep: int = 0) -> dict:
    """給不需要走勢圖的清單用，縮小 json。"""
    d = dict(d)
    if keep <= 0:
        d.pop("history", None)
    else:
        d["history"] = d.get("history", [])[-keep:]
    return d
