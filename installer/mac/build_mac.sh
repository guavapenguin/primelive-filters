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

echo "[4/4] 做發佈 dmg(app+開播腳本+內附OBS安裝檔+說明)..."
STAGE="$ENG/dist/dmg_stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
cp "$HERE/golive_mac.command" "$HERE/setup_mac.sh" "$STAGE/"
chmod +x "$STAGE/golive_mac.command" "$STAGE/setup_mac.sh"
# 內附 OBS 官方安裝檔(Apple Silicon;Intel 機器會自動改抓官方 Intel 版)
curl -sL --retry 3 -o "$STAGE/OBS-Studio.dmg" \
  "https://github.com/obsproject/obs-studio/releases/download/32.1.2/OBS-Studio-32.1.2-macOS-Apple.dmg"
cat > "$STAGE/使用說明.txt" <<'EOF'
primelive 一鍵開播 (macOS)
1) 把整個資料夾拖到桌面
2) 按住 control 點 golive_mac.command → 打開(只有第一次要這樣)
3) 它會自動裝好 OBS → 跳出視窗貼上你的「串流金鑰」
4) 系統跳出任何詢問都按「允許」
5) 視窗出現後:選濾鏡 → 按「● 開始直播」→ 回平台按「確認開播」
EOF
hdiutil create -volname "primelive" -srcfolder "$STAGE" -ov -format UDZO "$ENG/dist/primelive_mac.dmg"
echo "完成 -> $ENG/dist/primelive_mac.dmg"
echo ""
echo "== 首次在 Mac 上必驗清單 =="
echo "1. OBS 虛擬相機系統擴充要先在 OBS 按一次「啟動虛擬相機」啟用,引擎才吐得出畫面"
echo "2. VT 編碼器 id(setup_mac.sh 的 ENCODER_ID)推流測試;失敗改 obs_x264"
echo "3. 場景攝影機 av_capture 以 device_name 指定是否吃到(不行→OBS 內手動選一次)"
echo "4. 相機/麥克風權限:系統會跳授權,按允許"
