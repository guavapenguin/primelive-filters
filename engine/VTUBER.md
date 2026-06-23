# 完整 VTuber 虛擬人

primelive 有兩種「不露臉虛擬人」路線，依需求選：

## A. 引擎內建（輕量，免裝別的）
按鈕 **`虛擬分身·不露臉`**：把卡通大頭貼跟著你的頭移動/縮放/傾斜，並用 MediaPipe 的 **jawOpen** blendshape 讓分身**嘴巴跟著開合**（講話時會動）。
- 優點：零安裝、就在引擎裡、一鍵切換。
- 限制：是「會動嘴的大頭貼」，不是完整 Live2D 角色（沒有眨眼/複雜表情/身體）。
- 微調：`filters.json` 裡該預設的 `lipsync.y`（嘴在頭的高度比例）、`lipsync.w`（嘴寬比例）、`scale`/`y_off`（頭的大小位置）。

## B. 完整 Live2D 角色（VTube Studio，業界標準、免費）
要「會眨眼、做表情、可動的完整虛擬角色」就用 VTube Studio：
1. 安裝 **VTube Studio**（Steam 免費，Windows）。
2. 匯入一個 **Live2D 模型**（內建免費範例；或自製/購買角色）。
3. VTube Studio 用你的 **OBSBOT webcam** 做臉部追蹤，驅動角色的表情、嘴型、頭部。
4. 進 OBS：VTube Studio → 設定開 **Spout2** 輸出 → OBS 加「**Spout2 Capture**」來源（背景透明）；或用 OBS「視窗擷取」抓 VTube Studio 視窗。
5. 完成：觀眾看到的是你的 Live2D 虛擬人，完全不露臉。

> 註：VTube Studio 直接吃 webcam，**不經過 primelive 引擎**；兩者擇一即可。
> 引擎版 = 快速大頭分身；VTube Studio = 完整角色。要更進階可再接 Warudo（3D 虛擬人）。
