# primelive 直播濾鏡 — 夜間生成成果（2026-06-23 凌晨）

> 你睡前交代「由你操刀，我明早來看成品」。這是我用本機 ComfyUI（走 GPU、幾乎沒花你的 token）做出的第一批素材 + 我的檢查結論。
> 👉 一眼預覽：`obs/assets/_contact_sheet.jpg`（14 張拼成一張）

## 1. 做了什麼

### A. 14 張文青背景（「換背景」濾鏡素材）
SFW、無人物、無版權；模型 nightvisionxl SDXL，1344×768。位置 `obs/assets/backgrounds/`。

| 檔名 | 場景 |
|---|---|
| 01_book_cafe | 書香咖啡廳 |
| 02_rainy_window | 雨天窗邊閱讀角 |
| 03_sunlit_sofa | 暖陽閱讀沙發 |
| 04_vinyl_desk | 黑膠咖啡書桌 |
| 05_library | 復古圖書館 |
| 06_greenhouse | 植栽溫室咖啡 |
| 07_balcony_night | 星光陽台夜談 |
| 08_autumn_park | 秋日窗景 |
| 09_seaside_sunset | 海邊黃昏 |
| 10_artsy_shop | 文青選物店 |
| 11_morning_desk | 晨光書桌 |
| 12_fairytale_forest | 童話森林微光 |
| 13_jp_coffee_bar | 日系陶器／咖啡吧 |
| 14_evening_study | 夜晚暖燈書房 |

### B. 6 個文青氛圍 LUT（「調色」濾鏡，一檔一按鈕）
位置 `obs/assets/luts/`，產生器 `obs/filters/make_ambiance_luts.py`（改參數可重生）。
- 奶茶暖陽 `milktea_warm`｜底片灰調 `film_muted`｜陰雨藍灰 `rainy_bluegrey`｜童話柔光 `fairytale_soft`｜夜晚暖燈 `night_lamp`｜日系清新 `jp_fresh`

## 2. 品質檢查（我已逐張看過接觸表）
整體文青、溫暖、SFW、無人物、無明顯瑕疵或文字。13 比較像陶器層架、04 黑膠不明顯，但都可用、風格一致。**沒有需要急著重生的爛圖。**

## 3. 怎麼用
- **背景**：OBS 加「圖片」來源選 PNG 當底；要把你真人去背疊上去 → 裝 `obs-backgroundremoval` 外掛 或用已裝好的 NVIDIA Broadcast 去背，背景圖墊在人物下層。
- **LUT**：相機來源 → 濾鏡 → `+` 套用 LUT → 選 `.cube` → 量 30–70%。

## 4. 等你拍板 / 可調整（明早回我一句即可）
1. **風格**：只要這套「寫實照片」，還是也要一套「動漫插畫」版（用 waiIllustrious）？
2. **解析度**：要不要放大到 1920×1080（你有 upscaler 節點）？
3. **重生**：接觸表裡圈出不喜歡的，我重做。
4. **下一步素材**：要不要我接著做「透明動物耳朵貼紙」（走你裝的 BiRefNet 去背輸出 PNG）？
5. **數量**：背景要不要衝到 30–50 張，把「換背景」那層鋪滿？

## 5. 兩條背景工作流狀態
- **架構調查**：✅ 已完成。結論＝沿用現有 OBS 最省力：調色用內建 Apply LUT、換背景用 obs-backgroundremoval / NVIDIA Broadcast、貼紙/變形/瘦臉共用一顆臉部關鍵點引擎（自建 MediaPipe 或免費 Streamfog）。要精簡決策版跟我說。
- **100 濾鏡型錄**：✅ 已完成（98 個、10 家族、六層堆疊模型、12 hero）。可讀版 `obs/filters/CATALOG.md`、完整資料 `obs/filters/catalog_raw.json`。⚠️ 此型錄是「文青定調拍板前」生的，部分（霸總／惡魔／御姐魅惑／撩人互動）偏離文青/SFW，我已在 CATALOG.md 標出「品牌對齊待辦」，等你早上點頭再精修（不另開大 workflow，省 token）。

## 6. Token
夜間生成全走本機 GPU，幾乎不花 token。先前的「架構調查」工作流已自然跑完（那筆已消耗，不會再花）。
