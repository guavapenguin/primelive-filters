#!/bin/bash
# =============================================================================
#  primelive 一鍵開播 (macOS) v2 — 全自動,主播只貼金鑰
#  流程:首次設定(貼金鑰)→背景開OBS→自動啟用虛擬相機擴充→開引擎(直式視窗)
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
for c in "$HERE/primelive_filter.app" "$HERE/../primelive_filter.app" \
         "/Applications/primelive_filter.app" "$HOME/Applications/primelive_filter.app"; do
  if [ -d "$c" ]; then ENGINE="$c"; break; fi
done
[ -n "$ENGINE" ] || die "找不到濾鏡引擎 primelive_filter.app(請放在本檔旁邊或應用程式資料夾)。"
ENGINE_BIN="$ENGINE/Contents/MacOS/primelive_filter"

# ---- 首次:設定 OBS(唯一要主播動手的=貼金鑰) ----
OBS_ROOT="$HOME/Library/Application Support/obs-studio"
PS_DIR="$HOME/Library/Application Support/PrimeStage"
if [ ! -d "$OBS_ROOT/basic/profiles/Prime Stage 直式" ] || [ "${1:-}" = "--setup" ]; then
  bash "$HERE/setup_mac.sh" || die "OBS 設定失敗。"
fi

# ---- 背景開 OBS(主播不用看它) ----
if ! pgrep -x OBS >/dev/null 2>&1; then
  open -a OBS --args --profile "Prime Stage 直式" --collection "Prime Stage 直式" --minimize-to-tray
fi

# ---- 首次:自動啟用 OBS 虛擬相機系統擴充(免主播動手;系統若跳權限請按「允許」) ----
VCAM_MARK="$PS_DIR/vcam_ok"
if [ ! -f "$VCAM_MARK" ]; then
  echo "[開播] 首次啟用虛擬相機擴充(系統若跳出詢問請按「允許」)..."
  if "$ENGINE_BIN" --obs-vcam-kick; then
    mkdir -p "$PS_DIR"; touch "$VCAM_MARK"
  else
    echo "[note] 擴充啟用未完成,畫面若全黑請重跑一次本檔"
  fi
fi

# ---- 開引擎(直式視窗:濾鏡盤+開始直播鈕) ----
READY="/tmp/primelive_ready.flag"
rm -f "$READY"
open -n "$ENGINE" --args --ready-file "$READY"
for i in $(seq 1 80); do
  [ -f "$READY" ] && break
  sleep 0.5
done
echo "[開播] 完成。引擎視窗選濾鏡→按「● 開始直播」。"
