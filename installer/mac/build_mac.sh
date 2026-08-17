#!/bin/bash
# =============================================================================
#  在「Mac」上打包 primelive 引擎 .app + 發佈 dmg — 一行搞定:
#    git clone <repo> && cd obs/installer/mac && bash build_mac.sh
#  需求:macOS 12+、Xcode CLT、python3.11/3.12(brew install python@3.12)
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENG="$HERE/../../engine"
ASSETS="$HERE/../../assets"

PY="${PYTHON:-python3.12}"
command -v "$PY" >/dev/null || PY=python3
echo "[1/4] venv + 依賴($($PY --version))..."
cd "$ENG"
[ -d .venv-mac ] || "$PY" -m venv .venv-mac
./.venv-mac/bin/pip install -q --upgrade pip
./.venv-mac/bin/pip install -q -r requirements.txt pyinstaller

echo "[2/4] PyInstaller 打包(.app 視窗模式)..."
./.venv-mac/bin/pyinstaller --noconfirm --onedir --windowed --name primelive_filter \
  --collect-all mediapipe primelive_engine.py

APP="$ENG/dist/primelive_filter.app"
RES="$APP/Contents/MacOS"
echo "[3/4] 複製模型/設定/素材進 .app..."
cp "$ENG/face_landmarker.task" "$ENG/selfie_segmenter.task" "$ENG/filters.json" "$RES/"
cp -R "$ASSETS" "$RES/assets"

# ---- 簽章(有 Developer ID 憑證時;CI 由 SIGN_IDENTITY 傳入) ----
if [ -n "${SIGN_IDENTITY:-}" ]; then
  echo "[sign] codesign --deep --options runtime ($SIGN_IDENTITY)"
  # PyInstaller 產物內含大量 .so/.dylib,先逐一簽再簽整包(公證要求全部簽章)
  find "$APP" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 | \
    xargs -0 -n1 codesign --force --timestamp --options runtime --sign "$SIGN_IDENTITY" 2>/dev/null || true
  codesign --force --deep --timestamp --options runtime \
    --entitlements "$HERE/entitlements.plist" --sign "$SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP" && echo "[sign] verify OK"
else
  echo "[sign] 未提供 SIGN_IDENTITY,產出未簽章版(Gatekeeper 會擋;正式發佈請設 CI Secrets)"
fi

echo "[4/4] 做發佈 dmg(app+開播腳本+內附OBS安裝檔+說明)..."
STAGE="$ENG/dist/dmg_stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
cp "$HERE/golive_mac.command" "$HERE/setup_mac.sh" "$STAGE/"
# 檔名改白話,同事看到就知道點哪個
mv "$STAGE/golive_mac.command" "$STAGE/開始直播（點我）.command"
chmod +x "$STAGE/開始直播（點我）.command" "$STAGE/setup_mac.sh"
# 內附 OBS 官方安裝檔(Apple Silicon;Intel 機器會自動改抓官方 Intel 版)
curl -sL --retry 3 -o "$STAGE/OBS-Studio.dmg" \
  "https://github.com/obsproject/obs-studio/releases/download/32.1.2/OBS-Studio-32.1.2-macOS-Apple.dmg"
cat > "$STAGE/先看我（4步驟）.txt" <<'EOF'
primelive 直播  ─  4 步驟

① 把這整個資料夾拖到「桌面」

② 打開資料夾，找到「開始直播（點我）」
   → 第一次：按住鍵盤 control 鍵、同時點它一下 → 選單選「打開」→ 再按一次「打開」
   → 之後就直接點兩下就好

③ 等它跑（第一次會自動安裝需要的東西，1～3 分鐘）
   → 跳出視窗時，貼上你的「串流金鑰」（在直播主後台 → 設定 → OBS平台金鑰 → 複製）
   → 電腦如果問你「要允許嗎」，一律按「允許」或「好」

④ 出現直播視窗：
   下面一排照片＝濾鏡，左右滑動、點一下就套用
   按紅色「● 開始直播」→ 回到平台網頁按「確認開播」→ 上線！

結束直播：平台按「停止直播」→ 直播視窗再按一次紅色按鈕 → 關掉視窗


── 如果卡住 ──
・「無法打開，因為無法驗證開發者」→ 按「取消」，回到②，記得要按住 control 再點
・畫面全黑：關掉重點一次「開始直播（點我）」
・其他狀況：整個畫面截圖傳給小編
EOF
hdiutil create -volname "primelive" -srcfolder "$STAGE" -ov -format UDZO "$ENG/dist/primelive_mac.dmg"
if [ -n "${SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$ENG/dist/primelive_mac.dmg" && echo "[sign] dmg signed"
fi
echo "完成 -> $ENG/dist/primelive_mac.dmg"
echo ""
echo "== 首次在 Mac 上必驗清單 =="
echo "1. OBS 虛擬相機系統擴充要先在 OBS 按一次「啟動虛擬相機」啟用,引擎才吐得出畫面"
echo "2. VT 編碼器 id(setup_mac.sh 的 ENCODER_ID)推流測試;失敗改 obs_x264"
echo "3. 場景攝影機 av_capture 以 device_name 指定是否吃到(不行→OBS 內手動選一次)"
echo "4. 相機/麥克風權限:系統會跳授權,按允許"
