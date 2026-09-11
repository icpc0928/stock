# 每日市場報告（台股 × 美股）

每天兩份 HTML 報告：**08:30 早報**（昨夜美股 + 今日台股展望）、**15:30 午報**（台股收盤總結 + 美股盤前觀察）。
資料由 Python 抓取、評論由 Claude Code 撰寫、版面由 Jinja2 + Plotly 組出，全部在本機執行。

```
fetch/        抓資料 → data/<日期>-<am|pm>.json      （yfinance、TWSE 官方 JSON、Google News RSS）
.claude/      /daily-brief skill → analysis/<key>.json（Claude 的結構化評論）
build/        組版 → docs/<key>.html + index.html + latest.html + manifest.json（Plotly 互動圖、深淺色、手機可讀）
run.sh        一鍵串起三步 + git push 到 GitHub Pages；launchd/ 是排程設定
.github/      GitHub Actions workflow：每天 08:30 / 15:30 在雲端跑完整流程並推上 Pages（正式排程）
config.yaml   自選清單、掃描範圍、新聞關鍵字、輸出選項 — 改這裡就好
claude-config/ .claude/ 的原始副本（skill 與 command）；改完記得 cp 回 .claude/
```

## 安裝（一次）

```bash
cd ~/IdeaProjects/stock
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
chmod +x run.sh launchd/install.sh
```

## 先看版面（不連網、不用 Claude）

```bash
./run.sh am --fixture --no-ai --no-push   # 用示範資料組一份，會自動開瀏覽器
```

## 第一次真實資料測試

```bash
./run.sh am --no-ai --no-push        # 只抓資料 + 組版，先確認資料來源都通
./run.sh am                          # 完整流程（含 claude -p "/daily-brief am"）
```

看 `logs/` 可以知道哪一段失敗。TWSE 的欄位偶爾會改，`fetch/tw.py` 裡每個表都是獨立 try，缺一段不會整份失敗。

## 發布到 GitHub Pages（一次設定）

```bash
cd ~/IdeaProjects/stock
git init -b main && git add -A && git commit -m "init"
gh repo create stock --public --source=. --push      # 沒裝 gh 就到 github.com 手動建 repo 再 git remote add
```

然後到 repo **Settings → Pages → Build and deployment**：Source 選 *Deploy from a branch*，Branch 選 `main` / `/docs`，存檔。
一兩分鐘後網站會在 `https://<你的帳號>.github.io/stock/`，`latest.html` 永遠指向最新一份，適合加到手機書籤。

之後每次 `./run.sh am|pm` 組版完會自動 `git add docs data analysis → commit → push`；不想推就加 `--no-push`，或把 `config.yaml` 的 `publish.git_push` 改成 `false`。

## 排程：GitHub Actions（正式）

`.github/workflows/daily-report.yml` 每個交易日 08:30 / 15:30（台北）在 GitHub 的機器上跑 `fetch → claude → build → push`，Mac 關機也沒關係。

一次設定：

1. 在 Mac 執行 `claude setup-token`，複製產生的 token。
2. GitHub repo → Settings → Secrets and variables → Actions → New repository secret：名稱 `CLAUDE_CODE_OAUTH_TOKEN`，貼上 token。
3. `git push` 這個 workflow 之後，到 Actions 頁面 → daily-report → Run workflow，先勾 `skip_ai` 跑一次確認資料抓得到（TWSE 對境外 IP 有時會擋），再不勾跑一次看完整流程。

注意：
- Actions 的排程可能晚 5–15 分鐘，不保證準時。
- Actions 會直接 commit 到 main，本機要跑之前先 `git pull`。
- `config.yaml` 的 `publish.git_push` 已設為 false，本機 `./run.sh` 只產生檔案不推；要推就自己 `git push`。

### 備用：Mac launchd（已停用）

```bash
./launchd/install.sh                 # 裝回 08:30 / 15:30 的本機排程（記得把 publish.git_push 改回 true）
./launchd/install.sh remove          # 移除
```

## 自選股 / 掃描範圍

改 `config.yaml`：

- `watchlist.tw` / `watchlist.us`：固定追蹤，每份報告有專屬卡片（走勢、均線、法人、新聞、AI 一句評）。
- `auto_movers`：漲跌榜 / 成交金額榜 / 量能放大榜的檔數與門檻。
- `us_universe`：美股掃描的股票池。
- AI 的「值得觀察」名單不依賴自選清單，每份都會有。

## 之後要嵌進自己的網站

每次執行都有三種產物，資料與呈現是分開的：

| 檔案 | 內容 | 用途 |
|---|---|---|
| `data/<key>.json` | 原始行情、法人、新聞 | 自己畫圖 |
| `analysis/<key>.json` | Claude 評論（schema 在 `analysis/schema.json`） | 前端直接渲染 |
| `docs/<key>.html` | 組好的頁面（Plotly 走 CDN） | 直接 iframe 或靜態託管 |
| `docs/manifest.json` | 所有報告的清單：日期、headline、摘要、情緒、值得觀察、主要指數漲跌 | 前端首頁 / 列表 |

`python3 -m build.build --session am --inline` 會把 plotly.js 內嵌（離線可看，+4MB）。

## 免責

資料來自公開來源，AI 評論僅供個人參考，不構成投資建議。
