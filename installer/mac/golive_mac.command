#!/bin/bash
# =============================================================================
#  primelive 一鍵開播 (macOS) v2 — 全自動,主播只貼金鑰
#  流程:首次設定(貼金鑰)→背景開OBS→自動啟用虛擬相機擴充→開引擎(直式視窗)
# =============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# 若在唯讀映像檔(dmg)裡被直接點開:自動複製整包到桌面,改從桌面那份執行(映像檔內 Gatekeeper 更嚴、且無法寫入)
case "$HERE" in
  /Volumes/*)
    DEST="$HOME/Desktop/primelive"
    osascript -e 'display dialog "第一次使用:正在把 primelive 複製到桌面(約 10 秒),之後請從桌面的「primelive」資料夾點「開始直播（點我）」。" buttons {"好"} default button 1 giving up after 6' >/dev/null 2>&1 || true
    rm -rf "$DEST"; mkdir -p "$DEST"
    cp -R "$HERE"/. "$DEST"/
    xattr -dr com.apple.quarantine "$DEST" >/dev/null 2>&1 || true
    open "$DEST"
    exec bash "$DEST/$(basename "$0")" "$@"
    ;;
esac

# 內部試用版(未簽章):第一步替本資料夾解除「來自網路的隔離」,讓引擎 .app 能開(正式版簽章後不需要)
xattr -dr com.apple.quarantine "$HERE" >/dev/null 2>&1 || true

die() {
  osascript -e "display dialog \"$1\" buttons {\"OK\"} with icon stop with title \"primelive 開播\"" >/dev/null 2>&1 || true
  echo "[錯誤] $1"; exit 1
}

# ---- OBS:沒裝就自動裝(內附安裝檔優先,否則依晶片自動下載官方版) ----
OBS_URL_ARM="https://github.com/obsproject/obs-studio/releases/download/32.1.2/OBS-Studio-32.1.2-macOS-Apple.dmg"
OBS_URL_INTEL="https://github.com/obsproject/obs-studio/releases/download/32.1.2/OBS-Studio-32.1.2-macOS-Intel.dmg"
OBS_APP="/Applications/OBS.app"
[ -d "$OBS_APP" ] || OBS_APP="$HOME/Applications/OBS.app"
if [ ! -d "$OBS_APP" ]; then
  echo "[開播] 第一次使用,自動安裝 OBS(約 1~3 分鐘,請稍候)..."
  DMG=""
  for c in "$HERE/OBS-Studio.dmg" "$HERE/../OBS-Studio.dmg"; do
    [ -f "$c" ] && DMG="$c" && break
  done
  if [ -z "$DMG" ]; then
    if [ "$(uname -m)" = "arm64" ]; then U="$OBS_URL_ARM"; else U="$OBS_URL_INTEL"; fi
    DMG="/tmp/OBS-Studio.dmg"
    curl -sL --retry 3 --connect-timeout 30 -o "$DMG" "$U" || die "OBS 下載失敗,請檢查網路後重新執行。"
  fi
  MNT="/tmp/obs_mount_$$"
  hdiutil attach "$DMG" -nobrowse -quiet -mountpoint "$MNT" || die "OBS 安裝檔開啟失敗。"
  DEST="/Applications"; [ -w "$DEST" ] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
  cp -R "$MNT/OBS.app" "$DEST/" || { hdiutil detach "$MNT" -quiet; die "OBS 安裝失敗(磁碟空間或權限)。"; }
  hdiutil detach "$MNT" -quiet
  OBS_APP="$DEST/OBS.app"
  echo "[開播] OBS 安裝完成。"
fi
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
  open -a "$OBS_APP" --args --profile "Prime Stage 直式" --collection "Prime Stage 直式" --minimize-to-tray
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
