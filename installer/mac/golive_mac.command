#!/bin/bash
# =============================================================================
#  primelive 一鍵開播 (macOS)  — 對應 Windows golive.ps1 v8
#  雙擊執行:首次自動設定(貼金鑰)→啟動引擎(直式視窗+濾鏡盤+開播鈕)→背景開 OBS
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

die() {
  osascript -e "display dialog \"$1\" buttons {\"OK\"} with icon stop with title \"primelive 開播\"" >/dev/null 2>&1 || true
  echo "[錯誤] $1"; exit 1
}

# ---- 找 OBS 與引擎 ----
OBS_APP="/Applications/OBS.app"
[ -d "$OBS_APP" ] || die "找不到 OBS。請先到 https://obsproject.com/ 安裝 OBS(Apple Silicon 需 31.1 以上),裝好後重新執行。"
ENGINE=""
for c in "$HERE/../primelive_filter.app" "$HERE/primelive_filter.app" \
         "/Applications/primelive_filter.app" "$HOME/Applications/primelive_filter.app"; do
  if [ -d "$c" ]; then ENGINE="$c"; break; fi
done
[ -n "$ENGINE" ] || die "找不到濾鏡引擎 primelive_filter.app(請放在本檔旁邊或 /Applications)。"

# ---- 首次:設定 OBS(貼金鑰) ----
OBS_ROOT="$HOME/Library/Application Support/obs-studio"
if [ ! -d "$OBS_ROOT/basic/profiles/Prime Stage 直式" ] || [ "${1:-}" = "--setup" ]; then
  bash "$HERE/setup_mac.sh" || die "OBS 設定失敗。"
fi

# ---- 啟動引擎(等虛擬攝影機) ----
READY="/tmp/primelive_ready.flag"
rm -f "$READY"
open -n "$ENGINE" --args --ready-file "$READY"
echo "[開播] 等引擎虛擬攝影機就緒(最多40秒)..."
for i in $(seq 1 80); do
  [ -f "$READY" ] && break
  sleep 0.5
done

# ---- 背景開 OBS(主播不用看它;引擎視窗有「開始直播」鈕) ----
if ! pgrep -x OBS >/dev/null 2>&1; then
  open -a OBS --args --profile "Prime Stage 直式" --collection "Prime Stage 直式" --minimize-to-tray
fi
echo "[開播] 完成。引擎視窗選濾鏡→按「● 開始直播」。"
