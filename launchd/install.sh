#!/usr/bin/env bash
# 安裝 / 移除 launchd 排程
#   ./launchd/install.sh          安裝（08:30 早報、15:30 午報，週一到週日都會跑；假日抓到的是最近交易日）
#   ./launchd/install.sh remove   移除
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST" logs
for s in am pm; do
  label="com.leo.stock.$s"
  if [[ "${1:-}" == "remove" ]]; then
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    rm -f "$DEST/$label.plist"; echo "已移除 $label"
  else
    sed "s#/Users/leo/IdeaProjects/stock#$(pwd)#g; s#/Users/leo#$HOME#g" "launchd/$label.plist" > "$DEST/$label.plist"
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$DEST/$label.plist"
    echo "已安裝 $label → $DEST/$label.plist"
  fi
done
[[ "${1:-}" == "remove" ]] || launchctl list | grep com.leo.stock || true
echo "手動觸發測試：launchctl kickstart -k gui/$(id -u)/com.leo.stock.am"
