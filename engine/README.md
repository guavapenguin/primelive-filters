# primelive 一鍵濾鏡引擎（自建一體，方案 B）

> 決策(2026-06-23)：自建一體引擎，本地 MediaPipe（非雲端 API）OK。見 `../filters/ENGINE_DECISION.md`。

## 架構
```
OBSBOT 攝影機
  → MediaPipe FaceLandmarker(478 點 + 52 blendshape，本地、GPU)
  → 濾鏡管線：LUT 調色 + 貼紙(關鍵點貼) + 美顏/變形 + 換背景 + 換頭/虛擬人
  → 單一「primelive 虛擬攝影機」(pyvirtualcam → OBS 虛擬鏡頭)
  → 一排大按鈕 UI 一鍵切換
OBS 把「primelive 虛擬攝影機」當視訊來源 → 推流
```

## 技術棧
Python + MediaPipe(Tasks) + OpenCV + pyvirtualcam（吃已裝的 OBS 虛擬鏡頭）。

## 檔案
- `primelive_engine.py` — MVP 核心（攝影機 → 臉部追蹤 → LUT+貼紙 → 虛擬攝影機 → 一鍵切）
- `filters.json` — 濾鏡預設（數字鍵切換，路徑相對 `../assets/`）
- `requirements.txt` — 相依套件
- `.venv/` — 專屬虛擬環境（安裝腳本建立）

## 安裝 / 執行
```powershell
# 1) 建 venv + 裝套件（已在背景幫你跑）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 2) 取得模型 face_landmarker.task（見下）放本資料夾
# 3) 執行
.\.venv\Scripts\python.exe primelive_engine.py --camera 0
```
跑起來會有預覽窗 + 同時輸出虛擬攝影機。OBS → 視訊擷取裝置 選「OBS Virtual Camera」即可看到濾鏡後畫面。
按 `1`~`6` 切濾鏡、`q` 離開。

## 模型
`primelive_engine.py` 需要 MediaPipe 的 `face_landmarker.task`（純本地模型檔，約 3.7MB，跑在你機器上、不呼叫任何雲端）。
⚠️ 官方來源在 Google 儲存空間網域。考量你避免 Google 的偏好，安裝步驟會優先嘗試非 Google 鏡像；若取不到再請你決定是否一次性從官方下載。

## Roadmap
- [x] 決策：自建一體引擎 + 本地 MediaPipe
- [x] MVP 核心：攝影機 → 臉部追蹤 → LUT 調色 + 關鍵點貼紙 → 虛擬攝影機 → 一鍵切
- [x] 環境安裝 + 煙霧測試（venv 3.12、mediapipe 0.10.35、模型走 HuggingFace 鏡像；管線端到端 30fps 通過）
- [x] 美顏（磨皮：臉部雙邊濾波 + 凸包遮罩；瘦臉：下半臉 remap 內縮）
- [ ] 搞笑變形（大眼/大嘴 warp）
- [x] 換背景（MediaPipe SelfieSeg + 文青背景；遮罩每 N 格重算、預乘背景維持即時，~19fps@720p）
- [x] 效能優化：LUT 256³ 直查表；換背景遮罩每 3 格重用 + 縮圖分割；`--fast`(540p) 衝 fps（async 執行緒試過但 GIL 反效果已回退）
- [x] 搞笑變形（大眼/大嘴 bulge）：大眼娃娃 / 香腸嘴 / 哈哈鏡
- [x] 整顆頭替換（番薯/水豚/飯糰頭：2D 大頭貼錨定頭部、跟著縮放旋轉）
- [x] 不露臉（狐狸面具 / 虛擬分身大頭，蓋臉並追蹤）；完整 VTuber 可另接 VTube Studio
- [x] 完整虛擬人：引擎內建分身嘴型同步（jawOpen blendshape）+ VTube Studio 指南（`VTUBER.md`）
- [x] 一排大按鈕 GUI（預覽窗下方可點擊中文大按鈕 + 數字鍵；送進虛擬攝影機的畫面不含按鈕）
- [x] 打包成 .exe（PyInstaller onedir，dist 420MB 自帶 mediapipe+模型+素材，實跑 ~23fps 通過）；或雙擊 `啟動.bat`給主播一鍵安裝
