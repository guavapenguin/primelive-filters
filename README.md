# primelive · OBS 直播端設定（`obs` 子系統）

> primelive 專案的直播端設定中心：OBS 建置、相機/麥克風、美顏調色（LUT）與開台 SOP。
> 用途：① 內部測試直播流程 ② 之後可整理成給創作者的開台教學。
> 最後更新：2026-06-22

---

## 0. 器材 / 環境
- **攝影機**：OBSBOT Tiny Lite 3（USB AI 追蹤攝影機，鏡頭**內建麥克風** → 一條 USB 同時搞定畫面+收音，免擷取卡、免音訊介面）
- **GPU**：NVIDIA RTX 5070 Ti（錄影/直播用 **NVENC** 硬體編碼，CPU 幾乎不吃力）
- **OS**：Windows 11

## 1. 安裝（可直接跑 `install-tools.ps1`）
| 軟體 | 用途 | 狀態 / 來源 |
|---|---|---|
| OBS Studio | 錄影 / 推流主程式 | ✅ 已裝 v32.1.2（winget `OBSProject.OBSStudio`）|
| OBSBOT Center | 控制相機：AI 追蹤、自動構圖、手勢、變焦、HDR | ✅ 已裝 v2.0.14.33 |
| NVIDIA Broadcast | 去背、視訊降噪、Eye Contact（免費，吃 5070 Ti）| ✅ 已裝 v2.2.0 |

> OBSBOT Center 與 OBS **可同時開**：Center 控制相機，OBS 抓畫面，不衝突。

## 2. OBS 設定（先做本地錄影測試，不推流）
**2-1 首次啟動精靈**：選「我只想優化錄製，不會直播」；解析度 1920×1080、FPS 60（檔案太大再降 30）。

**2-2 加畫面**：來源 `+` → 視訊擷取裝置 → 裝置選 **「OBSBOT Tiny 3 Lite StreamCamera」**。
> 想要 Eye Contact / 去背：改選 **「Camera (NVIDIA Broadcast)」**，並先在 NVIDIA Broadcast App 把輸入設成 OBSBOT、開好效果。第一次測試建議先選 OBSBOT 本體，少一層比較好抓問題。

**2-3 音訊**：
- 設定 → 音訊 → 取樣率 **48 kHz**
- 麥克風選 **「OBSBOT Tiny 3 Lite Microphone」**（想降噪就改選 **「麥克風 (NVIDIA Broadcast)」**，並在 Broadcast App 把輸入設成 OBSBOT 麥）；**停用**桌面音訊與 Realtek 麥避免回音
- 講話音量落在 **-20 ~ -12 dB**

**2-4 錄影輸出（吃 GPU）**：
- 設定 → 輸出（簡易）：路徑自選；品質「高品質中等檔案大小」；格式 **mkv**（錄完用「檔案 → 重新封裝錄影」轉 mp4）；編碼器 **硬體 (NVENC, HEVC)** 或 NVENC H.264
- 設定 → 視訊：畫布/輸出 1920×1080，FPS 60/30

## 3. 濾鏡 / 美顏 / 調色
OBS 本身只能「**調色**」；瘦臉/磨皮要外掛一層。三層架構：

| 效果 | 在哪做 | 工具 |
|---|---|---|
| 調色（膚色/氛圍） | OBS 內 | ✅ 本資料夾 LUT + 色彩校正 |
| 磨皮 / 提亮 / 上妝 | 相機端 / 虛擬攝影機 App | OBSBOT Center、NVIDIA Broadcast、美顏 App |
| 瘦臉 / 大眼 / 改臉型 | 虛擬攝影機 App（ML 變形） | 美顏 App（多付費）/ 手機 App |

**3-1 套 LUT（調色，免費，已備好）** — 檔案在 `luts/`：
- `primelive_LUT_female_warm.cube` — 女款：暖膚、提亮、微粉柔光
- `primelive_LUT_male_clarity.cube` — 男款：冷峻、對比、輪廓清晰

載入：來源右鍵相機 → 濾鏡 → `+` 套用 LUT → 選 `.cube` → **量(Amount) 60~80%**（100% 太重）。要再微調，上面再加一個「色彩校正」。想換色調 → 改 `make_luts.py` 重生。

**3-2 美顏 / 瘦臉這層**：
- 先看 OBSBOT Center 有無內建美顏/HDR（Tiny 系列不一定有）
- NVIDIA Broadcast：去背 + 降噪 + Eye Contact（**沒有**磨皮/瘦臉）
- 要強磨皮/上妝/瘦臉 → 美顏虛擬攝影機 App（多付費）抓 OBSBOT 後輸出虛擬鏡頭給 OBS
- ⚠️ PC 即時「瘦臉」效果有限；手機美顏 App 才是瘦臉王道
- 💡 **免費神技**（職業主播都用）：① 柔光燈正面打光 ② 鏡頭擺**比眼睛略高、微微俯角** → 天然瘦下顎、放大眼、顯臉小

**3-3「讓男性更有魅力」配方**（保留輪廓、提氣色，別過度磨皮）：
- 調色：用**男款 LUT**
- 磨皮：輕度 **20~30%**，保留皮膚紋理
- 銳化：OBS 加「銳化」一點點 → 下顎線/眼神立體（男版 clarity）
- 瘦臉：只收**下顎**，搭俯角鏡位最自然
- 提亮：眼下、牙齒微提亮 → 精神有自信
- 燈光：側 45° 主光 + 弱補光 → 立體陰影（男性魅力靠骨架陰影，不靠磨皮）

## 4. 狀態 / 待辦
- [x] OBS Studio 安裝（v32.1.2）
- [x] 調色 LUT 生成（女款 / 男款）
- [x] NVIDIA Broadcast 安裝（v2.2.0）
- [x] 接上 OBSBOT Tiny 3 Lite，系統已偵測到（相機 + 內建麥）
- [x] 裝 OBSBOT Center（v2.0.14.33）
- [x] 文青濾鏡素材第一批：14 背景 + 6 氛圍 LUT（見 `assets/OVERNIGHT_NOTES.md`）
- [ ] OBS 加來源 + 音訊 + 錄影設定 ← **現在這步**
- [ ] 第一段本地錄影測試
- [ ] 套 LUT 後回報微調
- [ ] （未來）本地錄影 → 正式推流（平台 RTMP + 串流金鑰）

## 檔案
- `README.md` — 本文件（總設定指南）
- `install-tools.ps1` — 一鍵安裝 OBS + NVIDIA Broadcast，並開 OBSBOT 下載頁
- `make_luts.py` — LUT 產生器（改參數可重生）
- `luts/` — 調色 LUT（女款 / 男款）
