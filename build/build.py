"""組版：python3 -m build.build --session am|pm [--date YYYY-MM-DD] [--inline] [--no-open]

讀 data/<key>.json（行情）+ analysis/<key>.json（Claude 評論，可缺）→ reports/<key>.html + reports/index.html
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch.common import (ANALYSIS_DIR, DATA_DIR, ROOT, analysis_path, data_path, load_config, load_json,  # noqa: E402
                          now_tw, report_key, report_path)

log = logging.getLogger("build")
TEMPLATES = Path(__file__).resolve().parent / "templates"
SESSION_LABEL = {"am": "早報", "pm": "午報"}


# ----------------------------------------------------------------- 格式化 filters
def fmt_num(v: Any, n: int = 2) -> str:
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(v) >= 1000:
        return f"{v:,.{0 if abs(v) >= 10000 else n}f}"
    return f"{v:,.{n}f}"


def fmt_pct(v: Any, sign: bool = True) -> str:
    if v is None:
        return "—"
    v = float(v)
    return f"{'+' if sign and v > 0 else ''}{v:.2f}%"


def fmt_chg(v: Any, n: int = 2) -> str:
    if v is None:
        return "—"
    v = float(v)
    return f"{'+' if v > 0 else ''}{fmt_num(v, n)}"


def fmt_ntd(v: Any) -> str:
    """元 → 億 / 兆。"""
    if v is None:
        return "—"
    v = float(v)
    if abs(v) >= 1e12:
        return f"{v / 1e12:,.2f} 兆"
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.1f} 億"
    if abs(v) >= 1e4:
        return f"{v / 1e4:,.0f} 萬"
    return f"{v:,.0f}"


def fmt_shares(v: Any) -> str:
    """股 → 張（1 張 = 1000 股）。"""
    if v is None:
        return "—"
    v = float(v) / 1000
    if abs(v) >= 10000:
        return f"{'+' if v > 0 else ''}{v / 10000:,.1f} 萬張"
    return f"{'+' if v > 0 else ''}{v:,.0f} 張"


def updown(v: Any) -> str:
    """CSS class：台股慣例紅漲綠跌。"""
    if v is None:
        return "flat"
    v = float(v)
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def arrow(v: Any) -> str:
    if v is None:
        return ""
    v = float(v)
    return "▲" if v > 0 else ("▼" if v < 0 else "–")


def md(text: Optional[str]) -> str:
    if not text:
        return ""
    return markdown.markdown(text, extensions=["tables", "sane_lists"])


# ----------------------------------------------------------------- Plotly figures
def _line_fig(series: dict, title: str, days: int = 120) -> Optional[dict]:
    hist = (series or {}).get("history") or []
    if not hist:
        return None
    hist = hist[-days:]
    x = [h["date"] for h in hist]
    close = [h["close"] for h in hist]
    # MA20 / MA60 用 history 自己算（可能不足 60 天）
    def ma(n):
        out = []
        for i in range(len(close)):
            win = [c for c in close[max(0, i - n + 1): i + 1] if c is not None]
            out.append(round(sum(win) / len(win), 2) if len(win) == n else None)
        return out
    traces = [
        {"type": "scatter", "mode": "lines", "name": title, "x": x, "y": close,
         "line": {"width": 2, "color": "__S1__"}, "hovertemplate": "%{x}<br>%{y:,.2f}<extra></extra>"},
        {"type": "scatter", "mode": "lines", "name": "MA20", "x": x, "y": ma(20),
         "line": {"width": 1.2, "color": "__S2__"}, "hovertemplate": "MA20 %{y:,.2f}<extra></extra>"},
        {"type": "scatter", "mode": "lines", "name": "MA60", "x": x, "y": ma(60),
         "line": {"width": 1.2, "color": "__S3__"}, "hovertemplate": "MA60 %{y:,.2f}<extra></extra>"},
    ]
    n_ticks = 4
    step = max(1, (len(x) - 1) // (n_ticks - 1))
    tickvals = x[::step][:n_ticks]
    ticktext = [f"{int(d[5:7])}/{int(d[8:10])}" for d in tickvals]
    return {"data": traces, "layout": {"hovermode": "x unified",
                                       "xaxis": {"type": "category", "tickvals": tickvals, "ticktext": ticktext, "tickangle": 0, "showgrid": False},
                                       "yaxis": {"tickformat": ",.0f"}, "legend": {"orientation": "h", "y": 1.12, "x": 0}}}


def _bar_fig(labels: List[str], values: List[Optional[float]], suffix: str = "%", horizontal: bool = True) -> Optional[dict]:
    pairs = [(l, v) for l, v in zip(labels, values) if v is not None]
    if not pairs:
        return None
    if horizontal:
        pairs.sort(key=lambda p: p[1])
    labels = [p[0] for p in pairs]
    values = [p[1] for p in pairs]
    colors = ["__UP__" if v > 0 else "__DOWN__" for v in values]
    text = [f"{'+' if v > 0 else ''}{v:.2f}{suffix}" if suffix == "%" else f"{'+' if v > 0 else ''}{v:,.1f}{suffix}" for v in values]
    trace = {"type": "bar", "orientation": "h" if horizontal else "v",
             "x": values if horizontal else labels, "y": labels if horizontal else values,
             "marker": {"color": colors, "line": {"width": 0}}, "text": text, "textposition": "outside",
             "cliponaxis": False, "hovertemplate": "%{y}: %{text}<extra></extra>" if horizontal else "%{x}: %{text}<extra></extra>"}
    lo, hi = min(values), max(values)
    span = max(hi - lo, abs(hi), abs(lo), 0.01)
    pad = span * 0.35  # 留空間放文字標籤
    rng = [min(lo, 0) - pad, max(hi, 0) + pad]
    if horizontal:
        layout = {"bargap": 0.35, "xaxis": {"zeroline": True, "range": rng, "ticksuffix": suffix if suffix == "%" else ""},
                  "yaxis": {"automargin": True, "side": "left"}, "showlegend": False, "margin": {"l": 8, "r": 8, "t": 4, "b": 24}}
    else:
        layout = {"bargap": 0.4, "yaxis": {"zeroline": True, "range": rng}, "xaxis": {"automargin": True}, "showlegend": False}
    return {"data": [trace], "layout": layout}


def _spark(series: dict, days: int = 60) -> Optional[dict]:
    hist = (series or {}).get("history") or []
    if not hist:
        return None
    hist = hist[-days:]
    close = [h["close"] for h in hist]
    up = close[-1] >= close[0]
    return {"data": [{"type": "scatter", "mode": "lines", "x": [h["date"] for h in hist], "y": close,
                      "line": {"width": 1.5, "color": "__UP__" if up else "__DOWN__"}, "fill": "tozeroy",
                      "fillcolor": "__UPF__" if up else "__DOWNF__", "hovertemplate": "%{x}<br>%{y:,.2f}<extra></extra>"}],
            "layout": {"xaxis": {"visible": False}, "yaxis": {"visible": False, "range": [min(close) * 0.985, max(close) * 1.015]},
                       "margin": {"l": 0, "r": 0, "t": 0, "b": 0}, "showlegend": False, "hovermode": "x"}}


# ----------------------------------------------------------------- view model
def build_view(data: dict, analysis: Optional[dict], cfg: dict) -> dict:
    us, tw, meta = data.get("us") or {}, data.get("tw") or {}, data["meta"]
    session = meta["session"]
    figs: Dict[str, Any] = {}

    # KPI 列
    kpis = []
    taiex = tw.get("taiex") or {}
    if taiex:
        kpis.append({"label": "加權指數", "value": fmt_num(taiex.get("last")), "chg": taiex.get("change"), "pct": taiex.get("change_pct"), "sub": f"{tw.get('trade_date', '')}"})
    for sym in ("^GSPC", "^IXIC", "^SOX", "^DJI"):
        s = (us.get("indices") or {}).get(sym)
        if s:
            kpis.append({"label": s["name"], "value": fmt_num(s["last"]), "chg": s.get("change"), "pct": s.get("change_pct"), "sub": s.get("date", "")})
    for sym, n in (("^VIX", 2), ("TWD=X", 3), ("^TNX", 3)):
        s = (us.get("macro") or {}).get(sym)
        if s:
            kpis.append({"label": s["name"], "value": fmt_num(s["last"], n), "chg": s.get("change"), "pct": s.get("change_pct"), "sub": s.get("date", ""), "n": n})

    # 圖
    figs["taiex"] = _line_fig(taiex, "加權指數")
    for sym, key in (("^GSPC", "spx"), ("^IXIC", "ndx"), ("^SOX", "sox")):
        figs[key] = _line_fig((us.get("indices") or {}).get(sym), (us.get("indices") or {}).get(sym, {}).get("name", sym))
    tw_secs = tw.get("sectors") or []
    figs["tw_sectors"] = _bar_fig([s["name"].replace("類指數", "") for s in tw_secs], [s.get("change_pct") for s in tw_secs])
    us_secs = us.get("sectors") or {}
    figs["us_sectors"] = _bar_fig([f"{v['name']} {k}" for k, v in us_secs.items()], [v.get("change_pct") for v in us_secs.values()])
    inst = tw.get("institutional")
    if inst:
        figs["inst"] = _bar_fig(["外資", "投信", "自營商"], [round((inst.get(k) or 0) / 1e8, 1) for k in ("foreign_net", "trust_net", "dealer_net")], suffix=" 億", horizontal=False)
    for code, w in (tw.get("watchlist") or {}).items():
        figs[f"spark_tw_{code}"] = _spark(w)
    for code, w in (us.get("watchlist") or {}).items():
        figs[f"spark_us_{code}"] = _spark(w)
    figs = {k: v for k, v in figs.items() if v}

    # 自選股卡片
    a = analysis or {}
    notes = a.get("watchlist_notes") or {}
    news_w = (data.get("news") or {}).get("watchlist") or {}
    watch_cards = []
    for market, items in (("tw", tw.get("watchlist") or {}), ("us", us.get("watchlist") or {})):
        for code, w in items.items():
            watch_cards.append({"market": market, "code": code, "d": w, "fig": f"spark_{market}_{code}",
                                "note": notes.get(code), "news": news_w.get(code, [])[:3]})

    breadth = tw.get("breadth") or {}
    b_total = (breadth.get("up") or 0) + (breadth.get("down") or 0) + (breadth.get("flat") or 0)
    return {
        "cfg": cfg, "meta": meta, "session": session, "session_label": SESSION_LABEL.get(session, session),
        "title": cfg["report"].get("title", "每日市場報告"),
        "date": meta["date"], "generated_at": meta.get("generated_at", ""),
        "is_sample": meta.get("is_sample", False), "errors": meta.get("errors") or [],
        "kpis": kpis, "figs": figs, "figs_json": json.dumps(figs, ensure_ascii=False),
        "tw": tw, "us": us, "derived": data.get("derived") or {}, "news": data.get("news") or {},
        "breadth": breadth, "breadth_total": b_total,
        "watch_cards": watch_cards,
        "a": a, "has_analysis": bool(a),
        "sections": [{"title": s.get("title", ""), "html": md(s.get("body_md", ""))} for s in a.get("sections", [])],
        "plotly_inline": cfg["report"].get("plotly") == "inline",
    }


# ----------------------------------------------------------------- render
def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    env.filters.update({"num": fmt_num, "pct": fmt_pct, "chg": fmt_chg, "ntd": fmt_ntd, "shares": fmt_shares, "updown": updown, "arrow": arrow, "md": md})
    return env


def _plotly_js(inline: bool) -> str:
    if not inline:
        return '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>'
    cache = ROOT / "build" / "plotly.min.js"
    if not cache.exists():
        try:  # 優先用 plotly python 套件內附的 plotly.min.js
            import plotly
            src = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
            cache.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:  # noqa: BLE001
            import urllib.request
            log.info("下載 plotly.js 到 %s", cache)
            urllib.request.urlretrieve("https://cdn.plot.ly/plotly-2.35.2.min.js", cache)
    return "<script>" + cache.read_text(encoding="utf-8") + "</script>"


def _manifest_entry(key: str, data: dict, analysis: Optional[dict]) -> dict:
    """首頁與未來前端用的精簡摘要。"""
    us, tw, meta = data.get("us") or {}, data.get("tw") or {}, data["meta"]
    a = analysis or {}
    kpis = []
    t = tw.get("taiex") or {}
    if t:
        kpis.append({"label": "加權", "value": fmt_num(t.get("last")), "pct": t.get("change_pct")})
    for sym, label in (("^GSPC", "S&P"), ("^SOX", "費半"), ("^IXIC", "Nasdaq")):
        s = (us.get("indices") or {}).get(sym)
        if s:
            kpis.append({"label": label, "value": fmt_num(s.get("last")), "pct": s.get("change_pct")})
    return {
        "key": key, "date": key[:10], "session": key[-2:], "session_label": SESSION_LABEL.get(key[-2:], key[-2:]),
        "generated_at": meta.get("generated_at", ""), "is_sample": bool(meta.get("is_sample")),
        "headline": a.get("headline", ""), "summary": a.get("summary", [])[:3], "sentiment": a.get("sentiment") or {},
        "picks": [{"symbol": p.get("symbol"), "name": p.get("name"), "market": p.get("market"), "type": p.get("type")} for p in a.get("picks", [])],
        "kpis": kpis,
    }


def _manifest_path(cfg: dict) -> Path:
    return report_path("x", cfg).parent / "manifest.json"


def _load_manifest(cfg: dict) -> List[dict]:
    p = _manifest_path(cfg)
    if p.exists():
        try:
            return load_json(p)
        except Exception:  # noqa: BLE001
            pass
    return []


def render_report(key: str, cfg: dict) -> Path:
    data = load_json(data_path(key))
    ap = analysis_path(key)
    analysis = load_json(ap) if ap.exists() else None
    if analysis is None:
        log.warning("找不到 %s，報告將不含 AI 評論", ap)
    view = build_view(data, analysis, cfg)
    view["plotly_tag"] = _plotly_js(view["plotly_inline"])
    html = _env().get_template("report.html.j2").render(**view)
    out = report_path(key, cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    log.info("已寫入 %s (%.0f KB)", out, out.stat().st_size / 1024)
    # manifest.json：更新或新增這一筆
    items = [m for m in _load_manifest(cfg) if m.get("key") != key]
    items.append(_manifest_entry(key, data, analysis))
    items.sort(key=lambda m: m["key"], reverse=True)
    _manifest_path(cfg).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def render_index(cfg: dict) -> Path:
    out_dir = report_path("x", cfg).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    items = [m for m in _load_manifest(cfg) if (out_dir / f"{m['key']}.html").exists()]
    items.sort(key=lambda m: m["key"], reverse=True)
    latest = items[0] if items else None
    # 依月份分組
    months: Dict[str, List[dict]] = {}
    for it in items:
        months.setdefault(it["date"][:7], []).append(it)
    title = cfg["report"].get("title", "每日市場報告")
    site = cfg.get("publish", {}) or {}
    env = _env()
    html = env.get_template("index.html.j2").render(items=items, latest=latest, months=months, title=title, cfg=cfg,
                                                     site_desc=site.get("description", "台股 × 美股，每個交易日兩份 AI 市場短評"))
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    # latest.html：固定網址永遠指向最新報告
    if latest:
        (out_dir / "latest.html").write_text(
            f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0; url={latest["key"]}.html"><title>{title}</title>'
            f'<script>location.replace("{latest["key"]}.html")</script></head>'
            f'<body><a href="{latest["key"]}.html">{latest["date"]} {latest["session_label"]}</a></body></html>', encoding="utf-8")
    (out_dir / ".nojekyll").touch()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", choices=["am", "pm"], required=True)
    ap.add_argument("--date", help="YYYY-MM-DD，預設今天")
    ap.add_argument("--inline", action="store_true", help="把 plotly.js 內嵌進 html（離線可看）")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    if args.inline:
        cfg["report"]["plotly"] = "inline"
    d = datetime.strptime(args.date, "%Y-%m-%d") if args.date else now_tw(cfg)
    key = report_key(args.session, d, cfg)
    out = render_report(key, cfg)
    render_index(cfg)
    print(str(out))
    if cfg["report"].get("open_browser", True) and not args.no_open and os.environ.get("NO_OPEN") != "1":
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(out)], check=False)
            else:
                webbrowser.open(out.as_uri())
        except Exception as e:  # noqa: BLE001
            log.warning("無法自動開啟瀏覽器: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
