#!/usr/bin/env bash
# 每日市場報告 — 一鍵流程
#   ./run.sh am            早報：抓資料 → Claude 評論 → 組版 → 開瀏覽器
#   ./run.sh pm            午報（會等 TWSE 今日資料公布）
#   ./run.sh am --no-ai    跳過 Claude，只抓資料與組版（測試用）
#   ./run.sh am --fixture  用示範資料，不連網
#   ./run.sh am --date 2026-09-08   指定日期重跑（只重跑 AI 與組版；資料需已存在）
#   ./run.sh am --no-push  不推到 GitHub
set -euo pipefail
cd "$(dirname "$0")"

SESSION="${1:-}"; shift || true
[[ "$SESSION" == "am" || "$SESSION" == "pm" ]] || { echo "用法: ./run.sh am|pm [--no-ai] [--fixture] [--no-open] [--no-push] [--date YYYY-MM-DD]"; exit 1; }

NO_AI=0; FIXTURE=""; NO_OPEN=""; DATE=""; NO_PUSH="${NO_PUSH:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-ai) NO_AI=1 ;;
    --fixture) FIXTURE="--fixture" ;;
    --no-open) NO_OPEN="--no-open" ;;
    --no-push) NO_PUSH=1 ;;
    --date) DATE="$2"; shift ;;
    *) echo "未知參數 $1"; exit 1 ;;
  esac
  shift
done

# Python：優先用專案 venv
if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else PY=python3; fi
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

mkdir -p data analysis reports logs
LOG="logs/$(date +%Y-%m-%d)-$SESSION.log"
exec > >(tee -a "$LOG") 2>&1
echo "===== $(date '+%F %T') run.sh $SESSION ====="

if [[ -z "$DATE" ]]; then
  DATE="$($PY -c 'from fetch.common import now_tw,load_config; print(now_tw(load_config()).strftime("%Y-%m-%d"))')"
  WAIT=""; [[ "$SESSION" == "pm" && -z "$FIXTURE" ]] && WAIT="--wait"
  $PY -m fetch.run --session "$SESSION" $FIXTURE $WAIT
fi
KEY="$DATE-$SESSION"

if [[ "$NO_AI" == "0" ]]; then
  CLAUDE_BIN="$($PY -c 'from fetch.common import load_config; print(load_config()["ai"].get("command","claude"))')"
  MODEL="$($PY -c 'from fetch.common import load_config; print(load_config()["ai"].get("model",""))')"
  TOOLS="$($PY -c 'from fetch.common import load_config; print(load_config()["ai"].get("allowed_tools","Read,Write,WebSearch"))')"
  MAXT="$($PY -c 'from fetch.common import load_config; print(load_config()["ai"].get("max_turns",30))')"
  MODEL_ARG=(); [[ -n "$MODEL" ]] && MODEL_ARG=(--model "$MODEL")
  echo "--- Claude 分析 ($KEY) ---"
  "$CLAUDE_BIN" -p "/daily-brief $SESSION $DATE" --allowedTools "$TOOLS" --max-turns "$MAXT" "${MODEL_ARG[@]}" || echo "!! Claude 執行失敗，將以無評論版本組版"
  [[ -f "analysis/$KEY.json" ]] || echo "!! 找不到 analysis/$KEY.json"
fi

echo "--- 組版 ---"
$PY -m build.build --session "$SESSION" --date "$DATE" $NO_OPEN

# 發布到 GitHub Pages（config publish.git_push）
PUSH="$($PY -c 'from fetch.common import load_config; print(str(load_config().get("publish",{}).get("git_push",False)).lower())')"
if [[ "$PUSH" == "true" && "$NO_PUSH" != "1" ]]; then
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
    OUT_DIR="$($PY -c 'from fetch.common import load_config; print(load_config()["report"].get("output_dir","docs"))')"
    REMOTE="$($PY -c 'from fetch.common import load_config; print(load_config().get("publish",{}).get("remote","origin"))')"
    BRANCH="$($PY -c 'from fetch.common import load_config; print(load_config().get("publish",{}).get("branch","main"))')"
    echo "--- 發布 ($REMOTE/$BRANCH) ---"
    git pull --rebase -q "$REMOTE" "$BRANCH" 2>/dev/null || echo "（pull 失敗，繼續嘗試 push）"
    git add -A "$OUT_DIR" data analysis
    if git diff --cached --quiet; then
      echo "沒有變更，略過 push"
    else
      git commit -q -m "report: $KEY" && git push -q "$REMOTE" "$BRANCH" && echo "已推送 $KEY" || echo "!! git push 失敗（報告仍在本機 $OUT_DIR/）"
    fi
  else
    echo "（尚未設定 git remote，略過發布；見 README「發布到 GitHub Pages」）"
  fi
fi
echo "===== 完成 $(date '+%T') ====="
