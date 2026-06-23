# primelive 一鍵濾鏡 — 技術選型決策（2026-06-23）

> 來源：已完成的架構調查工作流（31 agent 查證），濃縮成可拍板版。前提：不懂技術的直播主、Windows、已用 OBS + OBSBOT Tiny 3 Lite + RTX 5070 Ti，文青/SFW，省成本省 token。

## 關鍵洞察：5 大支柱不必同一個引擎
| 支柱 | 最省力做法 | 成本 |
|---|---|---|
| 調色（氛圍 LUT） | OBS 內建 Apply LUT（已做 8 顆，一檔一按鈕） | 免費 ✓ |
| 換背景 | `obs-backgroundremoval`（RVM，免綠幕、RTX 100+fps）或已裝的 NVIDIA Broadcast | 免費 ✓ |
| 不露臉 / 虛擬人 | VTube Studio / Warudo（免費 VTuber，輸出虛擬攝影機進 OBS） | 免費 ✓ |
| 貼紙 / 搞笑變形 / 瘦臉美顏 / 整頭替換（番薯） | 需「臉部關鍵點 AR 引擎」← **唯一要拍板的點** | 視方案 |

## 三個方案（針對臉部 AR + 整體整合）
| | A 拼裝免費派 ⭐ | B 自建一體引擎 | C 買商用 SDK |
|---|---|---|---|
| 怎麼做 | OBS Apply LUT + obs-backgroundremoval + VTube Studio + Streamfog(免費 AR 貼紙/美顏虛擬攝影機) 組合 | 一個自家 App：MediaPipe Face Landmarker(478點+52 blendshape) 驅動貼紙/變形/美顏/換頭/avatar，整合 LUT+RVM，輸出單一「primelive 虛擬攝影機」 | 自家 App 但 AR 核心外購 Banuba / DeepAR，貼紙+美顏+變形+換背景一次到位 |
| 授權成本 | **$0** | **$0**（但要工程） | 付費：DeepAR ~$25→$1000/月(依 MAU)；Banuba 議價 |
| 工時 | 低（整合 + 包一鍵 UI） | 高（數週–數月，即時渲染 + 虛擬攝影機） | 中（整合 + 虛擬攝影機輸出） |
| 一鍵體驗 | 中（可能要開 2–3 個 App，用 OBS 場景/熱鍵包裝成「一鍵」感） | **最佳**（一個 App、一排大按鈕、品牌統一） | 佳 |
| 客製 ~128 濾鏡/換頭 | 受各 App 限制 | **最自由**（自家美術隨意擴充） | 高度客製(如番薯頭)不一定現成 |
| Google 紅線 | **可全避開**（換背景選 RVM 而非 MediaPipe 選項） | 核心是本地 MediaPipe（非雲端 API，需你接受）或換非 Google 替代 | 不碰 Google |

## 建議：分階段（A → B）
1. **階段 1（現在 → 上市）：方案 A，$0、最快、可全程避開 Google。** 把我們已生的背景 + LUT + VTube Studio 不露臉虛擬人 + 免費 AR 串成「可實際開台」的一鍵濾鏡 MVP，先讓主播愛上、驗證市場，零成本。
2. **階段 2（驗證有量後）：往方案 B 自建一體引擎收斂。** 當要把 ~128 濾鏡做成真正「一個 App、一排大按鈕、品牌統一」、含番薯頭/虛擬人時，投入自建（MediaPipe 核心）。
3. **方案 C** 當「想要高品質美顏/AR 又不想自建演算法」時的加速器（持續授權費）。

## 你要拍板的 2 件事
1. **路線**：分階段(A→B) / 直接自建(B) / 直接買(C)？
2. **本地 MediaPipe（Google 開源、非雲端 API）可否接受？** 不行的話，自建走非 Google 替代或改方案 C。

## Google 紅線備註
MediaPipe＝純本地、Apache-2.0、不呼叫任何 Google 雲端 API，與你避免的 Google Cloud API 不同類。階段 1（方案 A）整套可不碰 Google。
