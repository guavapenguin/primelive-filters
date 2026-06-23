# primelive · 直播一鍵濾鏡

> 給直播主用的 **OBS 一鍵濾鏡**：自建濾鏡引擎（輸出虛擬攝影機）+ 文青風素材 + 開台設定。
> 用途：**直播用**。21 個濾鏡點按鈕即切，畫面進 OBS 直接推流。
> 狀態：**✅ 全部完成，可直接開台。** 最後更新：2026-06-23

---

## ⭐ 主角：一鍵濾鏡引擎（`engine/`）

自建引擎（MediaPipe + OpenCV + pyvirtualcam），把攝影機畫面套濾鏡後輸出成 **「OBS Virtual Camera」**，OBS 當視訊來源就直接拿去直播。預覽窗下方一排**中文大按鈕，點一下就換濾鏡**（給不懂技術的主播）。

**21 個濾鏡**：原始｜調色（奶茶／童話／日系）｜貼紙（花圈）｜換背景（書香咖啡廳／童話森林／植栽溫室／星空）｜美顏（磨皮＋瘦臉）｜搞笑變形（大眼／香腸嘴／哈哈鏡）｜換頭（🥔番薯／水豚／飯糰）｜不露臉虛擬人（🦊狐狸面具／分身會跟著開合嘴）。

**怎麼跑**（repo 已含模型，免另外下載）：
```powershell
cd engine
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe primelive_engine.py     # 或雙擊 啟動.bat（順暢模式：啟動_順暢模式.bat = 540p 更順）
```
細節見 [engine/README.md](engine/README.md)；完整虛擬人（Live2D）見 [engine/VTUBER.md](engine/VTUBER.md)。

---

## 0. 器材 / 環境
- **攝影機**：OBSBOT Tiny 3 Lite（USB AI 追蹤，內建麥，一條線搞定畫面＋收音）
- **GPU**：NVIDIA RTX 5070 Ti（NVENC 硬體編碼，直播超省 CPU）
- **OS**：Windows 11

## 1. 軟體（可跑 `install-tools.ps1`）
| 軟體 | 用途 | 狀態 |
|---|---|---|
| OBS Studio | 直播推流主程式 | ✅ v32.1.2 |
| OBSBOT Center | 控制相機：AI 追蹤／自動構圖／手勢／變焦 | ✅ v2.0.14.33 |
| NVIDIA Broadcast | 去背／降噪／Eye Contact（可選） | ✅ v2.2.0 |

## 2. OBS 開台設定（直播）
**2-1 視訊來源**：來源 `+` → 視訊擷取裝置 → 選 **「OBS Virtual Camera」**（＝濾鏡引擎輸出的畫面）。
> 不想套引擎濾鏡時，可直接選「OBSBOT Tiny 3 Lite StreamCamera」。

**2-2 音訊**：設定 → 音訊 → 取樣率 **48 kHz**；麥克風選「OBSBOT Tiny 3 Lite Microphone」；**停用**桌面音訊與 Realtek 麥避免回音；講話音量 **-20 ~ -12 dB**。

**2-3 推流（直播）← 重點**：
- 設定 → **串流(Stream)** → 服務選平台（Twitch／YouTube／自訂 RTMP）→ 貼上該平台的**串流金鑰**。
- 設定 → **輸出** → 串流：編碼器 **NVENC**、位元率約 **6000 kbps**（1080p）、關鍵影格 2 秒。
- 設定 → **視訊**：1920×1080、FPS 30 或 60。
- 按右下 **「開始串流」** → 開台！

> 不需要錄影 —— 這套就是為了直播。（要錄也行，但不是重點。）

## 3. 濾鏡都在引擎裡了
調色／美顏／瘦臉／換背景／換頭／不露臉，**全部做進引擎**，點按鈕即用，不必再靠 OBS 內建或付費 App。素材在 `assets/`、型錄在 `filters/`。
- 微調濾鏡參數：改 `engine/filters.json`（每個濾鏡的 smooth／slim／eye／mouth／scale…）。
- 生更多背景/素材：本機 ComfyUI（見 `assets/OVERNIGHT_NOTES.md`）。

## 4. 狀態：✅ 全部完成
- [x] 器材（OBSBOT Tiny 3 Lite）+ 軟體（OBS／OBSBOT Center／NVIDIA Broadcast）
- [x] 文青素材：44 張背景（1080）+ 氛圍 LUT + 貼紙／換頭大頭貼
- [x] 一鍵濾鏡引擎：21 個濾鏡 + 中文大按鈕 GUI + 輸出 OBS 虛擬攝影機
- [x] 美顏（磨皮瘦臉）、搞笑變形、換頭、不露臉虛擬人（嘴型同步）
- [x] 打包成獨立 .exe（免裝 Python）+ 啟動.bat（含 `--fast` 540p 順暢模式）
- [x] 濾鏡型錄 ~128 + 文青 SFW 精修版
- [x] **可直接開台直播**

## 檔案結構
```
engine/      一鍵濾鏡引擎（主程式 + 模型 + 打包腳本 + 啟動.bat）
assets/      背景圖 / 貼紙 / 換頭大頭貼 / 氛圍 LUT
filters/     濾鏡型錄（CATALOG*.md）+ 架構決策 + LUT 產生器
luts/        早期女款/男款 LUT（已被引擎內建調色取代）
install-tools.ps1   一鍵安裝 OBS + NVIDIA Broadcast
```
