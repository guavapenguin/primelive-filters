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
# 首次設定的判斷=「金鑰是否已填」(不是資料夾存不存在:先前失敗的嘗試可能已建好空設定)
SVC="$OBS_ROOT/basic/profiles/Prime Stage 直式/service.json"
KEY_SET=""
if [ -f "$SVC" ]; then
  KEY_SET=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['settings'].get('key',''))" "$SVC" 2>/dev/null || \
            /usr/bin/plutil -extract settings.key raw -o - "$SVC" 2>/dev/null || echo "")
fi
CONFIG_VER="10"
VER_FILE="$PS_DIR/config_ver.txt"
CUR_VER=""; [ -f "$VER_FILE" ] && CUR_VER=$(tr -d '[:space:]' < "$VER_FILE")
if [ -z "$KEY_SET" ] || [ "${1:-}" = "--setup" ]; then
  bash "$HERE/setup_mac.sh" || die "OBS 設定失敗。"
elif [ "$CUR_VER" != "$CONFIG_VER" ]; then
  echo "[開播] 偵測到升級($CUR_VER→$CONFIG_VER),自動刷新設定(保留金鑰與設備)..."
  NOPROMPT=1 bash "$HERE/setup_mac.sh" || true   # 金鑰由 setup 自動沿用,不打擾
fi

# ---- 背景開 OBS(主播不用看它) ----
# 若已有「沒開遙控埠」的舊 OBS 在跑,先關掉(引擎會用正確參數重新帶起)
if pgrep -x OBS >/dev/null 2>&1 && ! nc -z 127.0.0.1 4455 2>/dev/null; then
  osascript -e 'quit app "OBS"' >/dev/null 2>&1 || true
  for i in $(seq 1 20); do pgrep -x OBS >/dev/null 2>&1 || break; sleep 0.5; done
  pgrep -x OBS >/dev/null 2>&1 && pkill -9 -x OBS 2>/dev/null || true
fi
rm -rf "$HOME/Library/Application Support/obs-studio/.sentinel" 2>/dev/null || true   # 清「未正常關閉」標記
# OBS 改由引擎啟動(帶 --websocket_port/--websocket_password,並輪詢到通),這裡不再開,避免雙開

# ---- 首次:自動啟用 OBS 虛擬相機系統擴充(免主播動手;系統若跳權限請按「允許」) ----
VCAM_MARK="$PS_DIR/vcam_ok"
vcam_ready() {   # OBS 虛擬相機擴充是否已啟用(systemextensionsctl 列出且 activated)
  systemextensionsctl list 2>/dev/null | grep -i "obs" | grep -qi "activated enabled"
}
if [ ! -f "$VCAM_MARK" ] && ! vcam_ready; then
  echo "[開播] 首次啟用虛擬相機擴充..."
  "$ENGINE_BIN" --obs-vcam-kick >/dev/null 2>&1 || true
  # 等使用者在系統設定按允許(最多 2 分鐘,期間每 3 秒檢查一次)
  if ! vcam_ready; then
    osascript -e 'display dialog "第一次使用要允許「OBS 虛擬相機」延伸功能(只做一次)：\n\n即將打開「系統設定」→ 找到 OBS(相機延伸功能)→ 把開關打開 → 輸入密碼\n\n完成後回來按「好」" buttons {"好"} default button 1 with icon note with title "primelive"' >/dev/null 2>&1 || true
    open "x-apple.systempreferences:com.apple.LoginItems-Settings.extension" 2>/dev/null || true
    for i in $(seq 1 40); do vcam_ready && break; sleep 3; done
  fi
fi
if vcam_ready; then
  mkdir -p "$PS_DIR"; touch "$VCAM_MARK"
  echo "[開播] 虛擬相機擴充已啟用"
else
  echo "[note] 虛擬相機擴充仍未啟用:引擎會以「無虛擬相機」模式開啟(視窗與濾鏡可用,推流畫面需擴充啟用後才會有)"
fi

# ---- 開引擎(直式視窗:濾鏡盤+開始直播鈕);記錄 log,崩潰時明確提示而非反覆重開 ----
READY="/tmp/primelive_ready.flag"
LOGF="$HOME/Library/Logs/primelive_engine.log"
rm -f "$READY"
# 用 open -a 以「前景 App」身分啟動:macOS 15 只對前景 App 彈相機授權框,背景 bash 直接叫二進位不會彈
# (log 由引擎自己寫到 %TEMP%/~/Library/Logs;這裡另存 open 的輸出)
open -a "$ENGINE" --args --ready-file "$READY" 2>>"$LOGF"
sleep 2
EPID=$(pgrep -n -f "primelive_filter.app/Contents/MacOS/primelive_filter" || echo "")
ok=""
# 只要引擎程序還活著就一直等(相機授權框開著多久都行);引擎真的結束才判失敗
for i in $(seq 1 1200); do         # 上限 10 分鐘
  [ -f "$READY" ] && ok=1 && break
  if [ -n "$EPID" ] && ! kill -0 "$EPID" 2>/dev/null; then break; fi   # 引擎已結束(崩潰)
  sleep 0.5
done
if [ -z "$ok" ]; then
  if [ -z "$EPID" ] || ! kill -0 "$EPID" 2>/dev/null; then
    osascript -e "display dialog \"濾鏡引擎啟動失敗(可能是相機權限被拒或未授權)。\n\n請到 系統設定 → 隱私權與安全性 → 相機/麥克風,把 primelive_filter 打開,再點一次「開始直播」。\n\n仍不行請把這個檔傳給小編:\n$LOGF\" buttons {\"好\"} with icon caution with title \"primelive\"" >/dev/null 2>&1 || true
    open -R "$LOGF" 2>/dev/null || true
    exit 1
  fi
  echo "[note] 引擎仍在啟動中(較慢的電腦需多等一下)"
fi
echo "[開播] 完成。引擎視窗選濾鏡→按「● 開始直播」。"
