---
description: 產生今日市場評論 analysis json（am 早報 / pm 午報）
argument-hint: "am|pm [YYYY-MM-DD]"
---

載入 `daily-brief` skill，依參數 `$ARGUMENTS`（第一個字是 session：am 或 pm；第二個可選，是日期 YYYY-MM-DD，預設今天台北時間）：

1. 讀取 `data/<日期>-<session>.json` 與 `config.yaml`。
2. 依 skill 的步驟撰寫評論。
3. 用 Write 工具把結果寫到 `analysis/<日期>-<session>.json`，嚴格符合 skill 裡的 schema。
4. 最後只印 `OK analysis/<日期>-<session>.json`。
