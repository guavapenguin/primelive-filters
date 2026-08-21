"""primelive 一鍵濾鏡引擎 — MVP 核心。

管線：攝影機 → MediaPipe(臉部關鍵點 + 人像分割) → 套濾鏡(換背景 + LUT 調色 + 關鍵點貼紙) → pyvirtualcam → OBS。
按數字鍵切換濾鏡(見 filters.json)，q 離開。

用法：
  .venv\\Scripts\\python.exe primelive_engine.py --camera 1
  .venv\\Scripts\\python.exe primelive_engine.py --frames 30 --no-window --preset 6   # 煙霧測試

需要模型：face_landmarker.task(臉) 與 selfie_segmenter.task(換背景)，放本資料夾。見 README。
"""
import os
import sys
import json
import time
import argparse
import threading

import numpy as np
import cv2
from PIL import Image as PILImage, ImageDraw as PILDraw, ImageFont as PILFont

# Windows 主控台預設 cp950：先把主控台輸出碼頁設成 UTF-8（.exe 直接跑或啟動 .bat
# 跑時中文都不亂碼，.bat 也不必再 chcp——避免 chcp 切碼頁造成批次檔解析錯位），
# 再把 Python stdout 改成 utf-8。
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
# --noconsole(視窗模式)打包時 stdout/stderr 是 None,print 會炸 → 導到日誌檔
if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    try:
        _logdir = (os.path.expanduser("~/Library/Logs") if sys.platform == "darwin"
                   else (os.environ.get("TEMP") or __import__("tempfile").gettempdir()))
        _log = open(os.path.join(_logdir, "primelive_engine.log"), "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _log
        if sys.stderr is None:
            sys.stderr = _log
    except Exception:
        import io
        sys.stdout = sys.stdout or io.StringIO()
        sys.stderr = sys.stderr or io.StringIO()
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if getattr(sys, "frozen", False):       # PyInstaller 打包後
    BASE = os.path.dirname(sys.executable)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
HERE = BASE
ASSETS = os.path.join(BASE, "assets")
if not os.path.isdir(ASSETS):
    ASSETS = os.path.join(os.path.dirname(BASE), "assets")  # 開發版：obs/assets
MODEL = os.path.join(BASE, "face_landmarker.task")
MODEL_SEG = os.path.join(BASE, "selfie_segmenter.task")

# ---------- LUT(.cube)----------
_lut_cache = {}
# 直查表精度：2^6=64 級/軸。實測對這批 .cube 與舊版 256 級輸出「零色差」(連乾淨漸層/背景都 0)，
# 但查表體積從每顆 50MB 縮到 0.8MB → CPU 快取命中大增，套色 39ms→15ms/格，是消除卡頓的關鍵。
LUT_BITS = 6
LUT_N = 1 << LUT_BITS
_LUT_SHIFT = 8 - LUT_BITS

def load_cube(path):
    """解析 .cube，並預先展開成 LUT_N^3 的 uint8 直查表(索引 [R>>shift,G,B])，每格套用只剩一次查表。"""
    if path in _lut_cache:
        return _lut_cache[path]
    size = None
    data = []
    with open(path, "r", encoding="ascii", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("TITLE") or s.startswith("DOMAIN"):
                continue
            if s.startswith("LUT_3D_SIZE"):
                size = int(s.split()[-1])
                continue
            p = s.split()
            if len(p) == 3:
                data.append((float(p[0]), float(p[1]), float(p[2])))
    table = np.array(data, dtype=np.float32).reshape(size, size, size, 3)  # [b,g,r,3]
    li = np.clip(np.round(np.arange(LUT_N) / (LUT_N - 1) * (size - 1)), 0, size - 1).astype(np.intp)
    big = (table[li.reshape(1, 1, LUT_N), li.reshape(1, LUT_N, 1), li.reshape(LUT_N, 1, 1)] * 255.0).astype(np.uint8)
    _lut_cache[path] = big   # shape (LUT_N,LUT_N,LUT_N,3)，索引 [R>>shift,G>>shift,B>>shift]
    return big

def apply_lut(rgb, big):
    return big[rgb[..., 0] >> _LUT_SHIFT, rgb[..., 1] >> _LUT_SHIFT, rgb[..., 2] >> _LUT_SHIFT]

# ---------- 貼紙 ----------
_stk_cache = {}

def load_sticker(path):
    if path not in _stk_cache:
        im = cv2.imread(path, cv2.IMREAD_UNCHANGED)   # BGRA
        if im is not None and im.shape[2] == 4:
            im = cv2.cvtColor(im, cv2.COLOR_BGRA2RGBA)
            # 自動裁切到不透明範圍：讓貼圖內容貼齊邊框，縮放/定位才會準
            a = im[..., 3]
            ys, xs = np.where(a > 16)
            if len(xs) > 0:
                im = im[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        _stk_cache[path] = im
    return _stk_cache[path]

def overlay(base, stk, cx, cy, target_w, angle):
    if stk is None:
        return base
    h0, w0 = stk.shape[:2]
    s = max(target_w / float(w0), 0.01)
    stk2 = cv2.resize(stk, (max(1, int(w0 * s)), max(1, int(h0 * s))), interpolation=cv2.INTER_AREA)
    h, w = stk2.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    stk2 = cv2.warpAffine(stk2, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    x = int(cx - w / 2.0); y = int(cy - h / 2.0)
    bh, bw = base.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(bw, x + w), min(bh, y + h)
    if x1 <= x0 or y1 <= y0:
        return base
    sx0, sy0 = x0 - x, y0 - y
    roi = base[y0:y1, x0:x1].astype(np.float32)
    sub = stk2[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)].astype(np.float32)
    a = sub[..., 3:4] / 255.0
    base[y0:y1, x0:x1] = (roi * (1 - a) + sub[..., :3] * a).astype(np.uint8)
    return base

def crown_placement(lms, W, H):
    def pt(i):
        return np.array([lms[i].x * W, lms[i].y * H])
    left, right, top = pt(234), pt(454), pt(10)
    face_w = float(np.linalg.norm(right - left))
    eye_r, eye_l = pt(33), pt(263)
    d = eye_l - eye_r
    angle = -float(np.degrees(np.arctan2(d[1], d[0])))
    cx = float(top[0])
    cy = float(top[1] - face_w * 0.35)
    return cx, cy, face_w * 1.5, angle

def head_placement(lms, W, H, scale=2.2, y_off=-0.15):
    """換頭 / 面具：把貼圖中心放在頭部、寬度=臉寬*scale、跟著頭傾斜。"""
    pts = _face_pts(lms, W, H)
    cx = float(pts[:, 0].mean())
    ymin, ymax = float(pts[:, 1].min()), float(pts[:, 1].max())
    face_w = float(pts[:, 0].max() - pts[:, 0].min())
    cy = float((ymin + ymax) / 2.0 + (ymax - ymin) * y_off)
    er = np.array([lms[33].x * W, lms[33].y * H])
    el = np.array([lms[263].x * W, lms[263].y * H])
    angle = -float(np.degrees(np.arctan2((el - er)[1], (el - er)[0])))
    return cx, cy, face_w * scale, angle

# ---------- 背景 ----------
_bg_cache = {}

def load_bg(path, W, H):
    key = (path, W, H)
    if key not in _bg_cache:
        im = cv2.imread(path, cv2.IMREAD_COLOR)
        if im is None:
            _bg_cache[key] = None
        else:
            im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
            _bg_cache[key] = cv2.resize(im, (W, H))
    return _bg_cache[key]

# ---------- 美顏（磨皮 + 瘦臉）----------

def _face_pts(lms, W, H):
    return np.array([[l.x * W, l.y * H] for l in lms], dtype=np.float32)

def slim_face(rgb, pts, strength):
    H, W = rgb.shape[:2]
    cx = float(pts[:, 0].mean())
    ymin, ymax = float(pts[:, 1].min()), float(pts[:, 1].max())
    x, y, wf, hf = cv2.boundingRect(pts.astype(np.int32))
    pad = int(0.35 * max(wf, hf))     # ROI 加大,留羽化空間
    X0, Y0 = max(0, x - pad), max(0, y - pad)
    X1, Y1 = min(W, x + wf + pad), min(H, y + hf + pad)
    if X1 <= X0 or Y1 <= Y0:
        return rgb
    ys, xs = np.mgrid[Y0:Y1, X0:X1].astype(np.float32)
    span = max(1.0, (ymax - ymin) * 0.7)
    vw = np.clip((ys - (ymin + (ymax - ymin) * 0.3)) / span, 0.0, 1.0)  # 下半臉權重高
    # ROI 邊界羽化:位移量在距框緣 pad 內線性淡出到 0,避免 remap 框邊出現接縫
    fade = max(1.0, float(pad))
    edge = np.minimum(np.minimum(xs - X0, (X1 - 1) - xs),
                      np.minimum(ys - Y0, (Y1 - 1) - ys))
    ew = np.clip(edge / fade, 0.0, 1.0)
    map_x = (xs + (xs - cx) * strength * vw * ew - X0).astype(np.float32)
    map_y = (ys - Y0).astype(np.float32)
    warped = cv2.remap(rgb[Y0:Y1, X0:X1], map_x, map_y,
                       interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    out = rgb.copy()
    out[Y0:Y1, X0:X1] = warped
    return out

# ---- 臉部關鍵點分組（MediaPipe FaceMesh 468/478 標準索引）----
LIPS_OUTER = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
LIPS_INNER = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
R_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]   # 影像左＝主角右眼
L_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]  # 影像右＝主角左眼
R_EYE_OUTER, L_EYE_OUTER = 33, 263     # 眼尾外角（魚尾紋起點）
R_EYE_BOT, L_EYE_BOT = 145, 374        # 眼睛下緣（眼下提亮錨點）
R_EYE_TOP = [246, 161, 160, 159, 158, 157, 173]   # 主角右眼上緣（眼影錨點）
L_EYE_TOP = [466, 388, 387, 386, 385, 384, 398]   # 主角左眼上緣
R_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]     # 主角右眉
L_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]  # 主角左眉
CHEEK_R, CHEEK_L = 50, 280             # 兩頰顴骨（腮紅）

def _ipts(lms, idx, W, H):
    return np.array([[lms[i].x * W, lms[i].y * H] for i in idx], np.float32)

def _roi_box(pts, W, H, pad_frac, base):
    x, y, w, h = cv2.boundingRect(pts.astype(np.int32))
    pad = int(pad_frac * base)
    return max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)

def _recolor_roi(roi, lmask, color, strength):
    """保亮度上色：保留原本明暗/紋理，只把色相換成 color（唇彩、腮紅共用）。"""
    f = roi.astype(np.float32)
    lum = f @ np.array([0.299, 0.587, 0.114], np.float32)
    cl = max(1.0, float(color[0]) * 0.299 + float(color[1]) * 0.587 + float(color[2]) * 0.114)
    tinted = np.clip(lum[..., None] * (np.array(color, np.float32) / cl), 0, 255)
    a = np.clip(lmask * strength, 0, 1)[..., None]
    return (f * (1 - a) + tinted * a).astype(np.uint8)

def _smooth_region(roi, lmask, d=11, s=60):
    """區域保邊柔化（魚尾紋/細紋用，比全臉磨皮更強）。"""
    sm = cv2.bilateralFilter(roi, d, s, s)
    a = np.clip(lmask, 0, 1)[..., None]
    return (roi.astype(np.float32) * (1 - a) + sm.astype(np.float32) * a).astype(np.uint8)

def apply_beauty(rgb, lms, params):
    """化妝管線。params 可含：
       smooth 磨皮、whiten 美白、wrinkle 魚尾紋/眼下細紋、brighten_eyes 亮眼、
       eye 大眼(細緻)、lipstick[r,g,b]+lip_strength 唇彩、blush[r,g,b]+blush_strength 腮紅、
       contour 修容、slim 瘦臉。缺哪個鍵＝該效果關閉，向後相容舊 preset。"""
    if not isinstance(params, dict):
        params = {"smooth": float(params)}
    H, W = rgb.shape[:2]
    pts = _face_pts(lms, W, H)
    face_w = float(pts[:, 0].max() - pts[:, 0].min())
    cxf = float(pts[:, 0].mean())
    out = rgb.copy()

    smooth = float(params.get("smooth", 0.0))
    whiten = float(params.get("whiten", 0.0))
    wrinkle = float(params.get("wrinkle", 0.0))
    brighten = float(params.get("brighten_eyes", 0.0))
    eye_big = float(params.get("eye", 0.0))
    contour = float(params.get("contour", 0.0))
    slim = float(params.get("slim", 0.0))

    # 1) 全臉磨皮（保邊雙邊濾波，遮罩限制在臉部凸包）
    if smooth > 0:
        x, y, wf, hf = cv2.boundingRect(pts.astype(np.int32))
        pad = int(0.15 * max(wf, hf))
        X0, Y0 = max(0, x - pad), max(0, y - pad)
        X1, Y1 = min(W, x + wf + pad), min(H, y + hf + pad)
        if X1 > X0 and Y1 > Y0:
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.fillConvexPoly(m, cv2.convexHull((pts - [X0, Y0]).astype(np.int32)), 1.0)
            m = cv2.GaussianBlur(m, (0, 0), 8.0) * smooth
            out[Y0:Y1, X0:X1] = _smooth_region(out[Y0:Y1, X0:X1], m, d=9, s=45)

    # 1.5) 美白（對應 FilterOnMe Skin.color 軸）：臉部凸包羽化遮罩內 screen 式提亮，保留紋理
    if whiten > 0:
        x, y, wf, hf = cv2.boundingRect(pts.astype(np.int32))
        pad = int(0.20 * max(wf, hf))
        X0, Y0 = max(0, x - pad), max(0, y - pad)
        X1, Y1 = min(W, x + wf + pad), min(H, y + hf + pad)
        if X1 > X0 and Y1 > Y0:
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.fillConvexPoly(m, cv2.convexHull((pts - [X0, Y0]).astype(np.int32)), 1.0)
            m = cv2.GaussianBlur(m, (0, 0), 10.0) * min(1.0, whiten)
            roi = out[Y0:Y1, X0:X1].astype(np.float32)
            lifted = roi + (255.0 - roi) * 0.42
            a = m[..., None]
            out[Y0:Y1, X0:X1] = (roi * (1 - a) + lifted * a).astype(np.uint8)

    # 2) 魚尾紋 / 眼下細紋（眼尾外側橢圓，強柔化；挖掉眼睛本體避免糊到眼睛）
    #    wrinkle 越高→sigma 越大、>0.85 做兩道保邊柔化，讓深一點的魚尾紋也抹得掉。
    if wrinkle > 0:
        w = float(wrinkle)
        sigma = int(70 + 60 * min(1.0, w))     # 70..130
        passes = 2 if w > 0.85 else 1
        for outer_i, eye_idx, sgn in ((R_EYE_OUTER, R_EYE, -1), (L_EYE_OUTER, L_EYE, +1)):
            ox, oy = lms[outer_i].x * W, lms[outer_i].y * H
            cx = ox + sgn * face_w * 0.05
            cy = oy + face_w * 0.03
            rx, ry = face_w * 0.13, face_w * 0.10
            X0, Y0 = int(max(0, cx - rx)), int(max(0, cy - ry))
            X1, Y1 = int(min(W, cx + rx)), int(min(H, cy + ry))
            if X1 <= X0 or Y1 <= Y0:
                continue
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.ellipse(m, (int(cx - X0), int(cy - Y0)), (int(rx), int(ry)), 0, 0, 360, 1.0, -1)
            cv2.fillConvexPoly(m, cv2.convexHull((_ipts(lms, eye_idx, W, H) - [X0, Y0]).astype(np.int32)), 0.0)
            m = cv2.GaussianBlur(m, (0, 0), 4.0) * min(1.0, w)
            roi = out[Y0:Y1, X0:X1]
            sm = roi
            for _ in range(passes):
                sm = cv2.bilateralFilter(sm, 13, sigma, sigma)
            a = np.clip(m, 0, 1)[..., None]
            out[Y0:Y1, X0:X1] = (roi.astype(np.float32) * (1 - a) + sm.astype(np.float32) * a).astype(np.uint8)

    # 3) 亮眼（眼下提亮，淡化黑眼圈與殘餘細紋陰影）
    if brighten > 0:
        for bot_i in (R_EYE_BOT, L_EYE_BOT):
            cx, cy = lms[bot_i].x * W, lms[bot_i].y * H + face_w * 0.05
            rx, ry = face_w * 0.10, face_w * 0.06
            X0, Y0 = int(max(0, cx - rx)), int(max(0, cy - ry))
            X1, Y1 = int(min(W, cx + rx)), int(min(H, cy + ry))
            if X1 <= X0 or Y1 <= Y0:
                continue
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.ellipse(m, (int(cx - X0), int(cy - Y0)), (int(rx), int(ry)), 0, 0, 360, 1.0, -1)
            m = cv2.GaussianBlur(m, (0, 0), 6.0) * brighten
            roi = out[Y0:Y1, X0:X1].astype(np.float32)
            out[Y0:Y1, X0:X1] = np.clip(roi + (28.0 * m)[..., None], 0, 255).astype(np.uint8)

    # 4) 唇彩（外唇減內唇＝不上到牙齒/口腔；保亮度上色）
    if params.get("lipstick"):
        outer = _ipts(lms, LIPS_OUTER, W, H)
        inner = _ipts(lms, LIPS_INNER, W, H)
        X0, Y0, X1, Y1 = _roi_box(outer, W, H, 0.18, face_w)
        if X1 > X0 and Y1 > Y0:
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.fillPoly(m, [(outer - [X0, Y0]).astype(np.int32)], 1.0)
            cv2.fillPoly(m, [(inner - [X0, Y0]).astype(np.int32)], 0.0)
            m = cv2.GaussianBlur(m, (0, 0), 2.0)
            out[Y0:Y1, X0:X1] = _recolor_roi(out[Y0:Y1, X0:X1], m, params["lipstick"], float(params.get("lip_strength", 0.5)))

    # 5) 腮紅（兩頰顴骨柔邊橢圓，保亮度上色＝不蓋掉膚質）
    if params.get("blush"):
        rx, ry = face_w * 0.15, face_w * 0.12
        pad = int(rx)   # ROI 留邊，讓高斯羽化能在框內完整淡出 → 不會出現方形硬邊
        for ci in (CHEEK_R, CHEEK_L):
            cx = lms[ci].x * W
            cy = lms[ci].y * H - face_w * 0.02   # 略往顴骨上提，貼近真實腮紅位置
            X0, Y0 = int(max(0, cx - rx - pad)), int(max(0, cy - ry - pad))
            X1, Y1 = int(min(W, cx + rx + pad)), int(min(H, cy + ry + pad))
            if X1 <= X0 or Y1 <= Y0:
                continue
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.ellipse(m, (int(cx - X0), int(cy - Y0)), (int(rx), int(ry)), 0, 0, 360, 1.0, -1)
            m = cv2.GaussianBlur(m, (0, 0), rx * 0.7)
            out[Y0:Y1, X0:X1] = _recolor_roi(out[Y0:Y1, X0:X1], m, params["blush"], float(params.get("blush_strength", 0.2)))

    # 5.5) 眼影（上眼瞼往眉方向的柔和色帶，保亮度上色）
    if params.get("eyeshadow"):
        es_s = float(params.get("eyeshadow_strength", 0.25))
        for top_idx in (R_EYE_TOP, L_EYE_TOP):
            lid = _ipts(lms, top_idx, W, H)
            if len(lid) < 3:
                continue
            up = lid.copy()
            up[:, 1] -= face_w * 0.055           # 往上延伸到眼摺
            poly = np.vstack([lid, up[::-1]])
            X0, Y0, X1, Y1 = _roi_box(poly, W, H, 0.12, face_w)
            if X1 <= X0 or Y1 <= Y0:
                continue
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.fillConvexPoly(m, cv2.convexHull((poly - [X0, Y0]).astype(np.int32)), 1.0)
            m = cv2.GaussianBlur(m, (0, 0), face_w * 0.03)
            out[Y0:Y1, X0:X1] = _recolor_roi(out[Y0:Y1, X0:X1], m, params["eyeshadow"], es_s)

    # 5.6) 眉毛（眉形區壓深＝更立體有神；男女通用，男生用低強度做「乾淨眉」）
    if params.get("brow"):
        bw_s = float(params.get("brow", 0.0))
        for bidx in (R_BROW, L_BROW):
            bp = _ipts(lms, bidx, W, H)
            if len(bp) < 3:
                continue
            X0, Y0, X1, Y1 = _roi_box(bp, W, H, 0.06, face_w)
            if X1 <= X0 or Y1 <= Y0:
                continue
            m = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.fillConvexPoly(m, cv2.convexHull((bp - [X0, Y0]).astype(np.int32)), 1.0)
            m = cv2.GaussianBlur(m, (0, 0), face_w * 0.012) * min(1.0, bw_s)
            roi = out[Y0:Y1, X0:X1].astype(np.float32)
            a = m[..., None]
            out[Y0:Y1, X0:X1] = (roi * (1 - 0.35 * a)).astype(np.uint8)   # 壓深 35%×強度

    # 6) 修容（臉部外側 ~45% 壓暗，做出收窄陰影；限中下半臉避免額頭/太陽穴變髒）
    if contour > 0:
        x, y, wf, hf = cv2.boundingRect(pts.astype(np.int32))
        pad = int(0.05 * max(wf, hf))
        X0, Y0 = max(0, x - pad), max(0, y - pad)
        X1, Y1 = min(W, x + wf + pad), min(H, y + hf + pad)
        if X1 > X0 and Y1 > Y0:
            mface = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            cv2.fillConvexPoly(mface, cv2.convexHull((pts - [X0, Y0]).astype(np.int32)), 1.0)
            mface = cv2.GaussianBlur(mface, (0, 0), 5.0)
            ys, xs = np.mgrid[Y0:Y1, X0:X1].astype(np.float32)
            lat = np.clip((np.abs(xs - cxf) / max(1.0, wf * 0.5) - 0.55) / 0.45, 0.0, 1.0)
            ymin = float(pts[:, 1].min())
            vw = np.clip((ys - (ymin + hf * 0.30)) / max(1.0, hf * 0.5), 0.0, 1.0)
            m = mface * lat * vw * contour
            roi = out[Y0:Y1, X0:X1].astype(np.float32)
            out[Y0:Y1, X0:X1] = (roi * (1 - 0.30 * m[..., None])).astype(np.uint8)

    # 6.5) 大眼（細緻版，對應 FilterOnMe FaceMorph.eyes 軸；搞笑大眼請用 warp）
    if eye_big > 0:
        for idx in (468, 473):   # 虹膜中心（478 點模型）
            if idx < len(lms):
                out = bulge(out, lms[idx].x * W, lms[idx].y * H,
                            face_w * 0.16, min(0.5, eye_big) * 0.55)

    # 7) 瘦臉（幾何 warp，最後做，讓上面所有妝感一起跟著變形）
    if slim > 0:
        out = slim_face(out, pts, slim)
    return out


# ---------- 搞笑變形（大眼 / 大嘴 bulge）----------

def bulge(rgb, cx, cy, R, strength):
    H, W = rgb.shape[:2]
    X0, X1 = max(0, int(cx - R)), min(W, int(cx + R))
    Y0, Y1 = max(0, int(cy - R)), min(H, int(cy + R))
    if X1 <= X0 or Y1 <= Y0:
        return rgb
    ys, xs = np.mgrid[Y0:Y1, X0:X1].astype(np.float32)
    dx, dy = xs - cx, ys - cy
    r = np.sqrt(dx * dx + dy * dy) / R
    f = np.where(r < 1.0, np.clip(r, 1e-3, 1.0) ** strength, 1.0).astype(np.float32)
    map_x = (cx + dx * f - X0).astype(np.float32)
    map_y = (cy + dy * f - Y0).astype(np.float32)
    warped = cv2.remap(rgb[Y0:Y1, X0:X1], map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    out = rgb.copy()
    out[Y0:Y1, X0:X1] = warped
    return out

def apply_warp(rgb, lms, eye=0.0, mouth=0.0):
    H, W = rgb.shape[:2]
    pts = _face_pts(lms, W, H)
    face_w = float(pts[:, 0].max() - pts[:, 0].min())
    out = rgb
    if eye > 0:
        for idx in (468, 473):  # 虹膜中心（478 點模型）
            if idx < len(lms):
                out = bulge(out, lms[idx].x * W, lms[idx].y * H, face_w * 0.13, eye)
    if mouth > 0:
        cx = (lms[13].x + lms[14].x) / 2.0 * W
        cy = (lms[13].y + lms[14].y) / 2.0 * H
        out = bulge(out, cx, cy, face_w * 0.18, mouth)
    return out


# ---------- 虛擬人嘴型同步（jawOpen blendshape）----------

def jaw_open(res):
    if res is not None and res.face_blendshapes:
        for c in res.face_blendshapes[0]:
            if c.category_name == "jawOpen":
                return float(c.score)
    return 0.0

def draw_mouth(out, cx, cy, tw, ang, openness, ls):
    yf = float(ls.get("y", 0.62))
    wf = float(ls.get("w", 0.16))
    mcx = int(cx)
    mcy = int(cy + tw * (yf - 0.5))
    mw = max(2, int(tw * wf / 2))
    mh = max(2, int(tw * wf * (0.15 + 1.2 * min(1.0, openness * 1.5)) / 2))
    cv2.ellipse(out, (mcx, mcy), (mw, mh), -ang, 0, 360, (120, 55, 65), -1)
    return out


# ---------- UI（大按鈕，含中文標籤）----------
_FONT_PATH = None

def _font(size):
    global _FONT_PATH
    if _FONT_PATH is None:
        _FONT_PATH = ""
        for fp in (r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\mingliu.ttc"):
            if os.path.exists(fp):
                _FONT_PATH = fp
                break
    try:
        return PILFont.truetype(_FONT_PATH, size) if _FONT_PATH else PILFont.load_default()
    except Exception:
        return PILFont.load_default()

_panel_cache = {}

# ---- 專業雙語面板：字型 / 分類色 / 漸層工具 ----
_uifont_cache = {}
def _uifont(kind, size):
    k = (kind, size)
    if k in _uifont_cache:
        return _uifont_cache[k]
    cand = {
        "zhb":  [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
                 "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"],
        "zh":   [r"C:\Windows\Fonts\msjh.ttc",   r"C:\Windows\Fonts\msyh.ttc",
                 "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Light.ttc"],
        "en":   [r"C:\Windows\Fonts\segoeui.ttf", "/System/Library/Fonts/Helvetica.ttc"],
        "ensb": [r"C:\Windows\Fonts\segoeuisb.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"],
    }.get(kind, [r"C:\Windows\Fonts\msjh.ttc", "/System/Library/Fonts/PingFang.ttc"])
    fnt = None
    for p in cand:
        if os.path.exists(p):
            try:
                fnt = PILFont.truetype(p, size); break
            except Exception:
                pass
    if fnt is None:
        fnt = _font(size)
    _uifont_cache[k] = fnt
    return fnt

_CAT_COLOR = {
    "basic": (150, 156, 168), "color": (122, 162, 247), "beauty": (233, 130, 155),
    "bg": (110, 196, 158), "acc": (240, 168, 120), "head": (230, 176, 92), "warp": (176, 142, 232),
}

def _vgrad_rrect(base, box, c1, c2, radius):
    """在 base(RGB PIL) 上貼一個上下漸層的圓角矩形。"""
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    grad = PILImage.new("RGB", (w, h))
    gd = PILDraw.Draw(grad)
    for i in range(h):
        t = i / max(1, h - 1)
        gd.line([(0, i), (w, i)], fill=tuple(int(c1[j] + (c2[j] - c1[j]) * t) for j in range(3)))
    mask = PILImage.new("L", (w, h), 0)
    PILDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    base.paste(grad, (x0, y0), mask)

def build_panel(presets, active, W):
    """專業雙語濾鏡面板（中文為主、英文在下；分類色條；active 用暖色漸層＋光暈）。
       只在 active 改變時重畫並快取。回傳 (面板BGR, 命中矩形, 高)。"""
    if active in _panel_cache:
        return _panel_cache[active]
    PADX, GAP = 16, 12
    cols = int(max(4, min(7, (W - PADX * 2 + GAP) // (215 + GAP))))
    cardw = (W - PADX * 2 - GAP * (cols - 1)) / cols
    cardh, hdrh = 66, 60
    rows = (len(presets) + cols - 1) // cols
    H = hdrh + PADX + rows * (cardh + GAP) - GAP + PADX

    BG = (17, 19, 24); CARD = (32, 36, 45); BORDER = (49, 54, 67)
    TXT = (244, 245, 248); TXT_EN = (150, 158, 173); TXT_KEY = (120, 127, 142)
    HDR = (23, 26, 34); ACC1 = (240, 178, 110); ACC2 = (226, 120, 110); GOLD = (233, 193, 122)

    pil = PILImage.new("RGB", (W, H), BG)
    d = PILDraw.Draw(pil, "RGBA")
    zhb = lambda s: _uifont("zhb", s); zh = lambda s: _uifont("zh", s)
    en = lambda s: _uifont("en", s); ensb = lambda s: _uifont("ensb", s)

    # 標題列
    d.rectangle([0, 0, W, hdrh], fill=HDR)
    d.text((PADX, 13), "primelive", font=ensb(24), fill=GOLD)
    plw = d.textlength("primelive", font=ensb(24))
    d.text((PADX + plw + 10, 18), "一鍵濾鏡", font=zhb(16), fill=TXT)
    d.text((PADX, 40), "點一下即換濾鏡　One-Tap Live Filters", font=zh(11), fill=TXT_EN)
    cur = presets[active]
    lbl = "目前 " + cur.get("name", "")
    lw = max(d.textlength(lbl, font=zhb(13)), d.textlength(cur.get("en", ""), font=en(10))) + 24
    _vgrad_rrect(pil, (W - PADX - lw, 12, W - PADX, hdrh - 12), ACC1, ACC2, 11)
    cxx = W - PADX - lw / 2
    d.text((cxx, 24), lbl, font=zhb(13), fill=(38, 26, 20), anchor="mm")
    d.text((cxx, 40), cur.get("en", ""), font=en(10), fill=(84, 54, 42), anchor="mm")

    rects = []
    y0 = hdrh + PADX
    for i, pr in enumerate(presets):
        r, c = divmod(i, cols)
        x = PADX + c * (cardw + GAP); y = y0 + r * (cardh + GAP)
        on = (i == active); acc = _CAT_COLOR.get(pr.get("cat", "basic"), (150, 156, 168))
        if on:
            _vgrad_rrect(pil, (x, y, x + cardw, y + cardh), ACC1, ACC2, 11)
            d.rounded_rectangle([x, y, x + cardw, y + cardh], radius=11, outline=(255, 225, 190, 140), width=1)
            name_c = (38, 26, 20); en_c = (96, 60, 44); key_bg = (255, 255, 255, 150); key_out = None; key_c = (150, 100, 60)
        else:
            d.rounded_rectangle([x, y, x + cardw, y + cardh], radius=11, fill=CARD, outline=BORDER, width=1)
            name_c = TXT; en_c = TXT_EN; key_bg = (44, 49, 61, 255); key_out = BORDER; key_c = TXT_KEY
        d.rounded_rectangle([x + 9, y + 12, x + 12, y + cardh - 12], radius=2, fill=(255, 255, 255, 210) if on else acc)
        tx = x + 22
        d.text((tx, y + 13), pr.get("name", ""), font=zhb(17), fill=name_c)
        d.text((tx, y + 40), pr.get("en", ""), font=en(10), fill=en_c)
        kb = str(pr["key"]).upper(); kw = d.textlength(kb, font=ensb(11))
        bx1 = x + cardw - 12; bx0 = bx1 - (kw + 14)
        d.rounded_rectangle([bx0, y + 11, bx1, y + 29], radius=5, fill=key_bg, outline=key_out, width=1)
        d.text(((bx0 + bx1) / 2, y + 20), kb, font=ensb(11), fill=key_c, anchor="mm")
        rects.append((int(x), int(y), int(x + cardw), int(y + cardh), i))

    panel = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    _panel_cache[active] = (panel, rects, H)
    return _panel_cache[active]


# ---------- OBS 遙控（obs-websocket v5,localhost 免密碼;讓主播不用看到 OBS）----------
class ObsControl:
    def __init__(self, port=4455):
        self.port = port
        self.password = ""
        self.streaming = False
        self.connected = False
        self.busy = False
        self.diag = ""
        try:   # 設定流程(setup.ps1)產生的連線資訊:埠+隨機密碼
            base = (os.environ.get("APPDATA", "") if sys.platform == "win32"
                    else os.path.expanduser("~/Library/Application Support"))
            cfg = json.load(open(os.path.join(base, "PrimeStage", "obsws.json"), encoding="utf-8"))
            self.port = int(cfg.get("port", self.port))
            self.password = cfg.get("password", "")
        except Exception:
            pass

    def _rpc(self, req_type, req_data=None):
        import websocket as _ws
        import uuid as _uuid
        import hashlib as _hl
        import base64 as _b64
        ws = _ws.create_connection("ws://127.0.0.1:%d" % self.port, timeout=3)
        try:
            hello = json.loads(ws.recv())                           # Hello
            ident = {"rpcVersion": 1}
            auth = (hello.get("d") or {}).get("authentication")
            if auth and self.password:                              # obs-websocket v5 認證
                sec = _b64.b64encode(_hl.sha256((self.password + auth["salt"]).encode()).digest()).decode()
                ident["authentication"] = _b64.b64encode(_hl.sha256((sec + auth["challenge"]).encode()).digest()).decode()
            ws.send(json.dumps({"op": 1, "d": ident}))              # Identify
            json.loads(ws.recv())                                   # Identified
            rid = str(_uuid.uuid4())
            req = {"requestType": req_type, "requestId": rid}
            if req_data:
                req["requestData"] = req_data
            ws.send(json.dumps({"op": 6, "d": req}))
            while True:
                m = json.loads(ws.recv())
                if m.get("op") == 7 and m["d"].get("requestId") == rid:
                    return m["d"]
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def toggle_stream_async(self):
        """非同步切換直播(不卡輸出迴圈);結果反映在 self.streaming/connected。"""
        if self.busy:
            return
        self.busy = True
        def run():
            try:
                d = self._rpc("ToggleStream")
                rd = d.get("responseData") or {}
                self.streaming = bool(rd.get("outputActive", not self.streaming))
                self.connected = True
            except Exception:
                self.connected = False
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    def ensure_obs_async(self):
        """背景:OBS 沒在跑或埠沒開→引擎自己把 OBS 帶起來(帶 websocket 參數),輪詢到通;
        連不上時把診斷寫進 log(OBS 是否活著/埠是否開/OBS log 尾)。"""
        if getattr(self, "_ensuring", False):
            return
        self._ensuring = True
        def run():
            import socket, subprocess, glob
            def port_open():
                try:
                    s = socket.create_connection(("127.0.0.1", self.port), timeout=1); s.close(); return True
                except Exception:
                    return False
            def clear_sentinel():
                # OBS「上次未正常關閉」標記(.sentinel):存在就停在安全模式詢問框(藏在系統匣沒人按→埠不開)
                base = (os.path.expanduser("~/Library/Application Support/obs-studio") if sys.platform == "darwin"
                        else os.path.join(os.environ.get("APPDATA", ""), "obs-studio"))
                sp = os.path.join(base, ".sentinel")
                try:
                    if os.path.isdir(sp):
                        import shutil as _sh; _sh.rmtree(sp, ignore_errors=True); print("[obs] 已清除 .sentinel")
                    elif os.path.isfile(sp):
                        os.remove(sp)
                except Exception as _e:
                    print("[obs] 清 sentinel 失敗: %s" % _e)
            try:
                if port_open():
                    self.connected = True; return
                self.diag = ""
                if sys.platform == "darwin":
                    running = subprocess.run(["pgrep", "-x", "OBS"], capture_output=True).returncode == 0
                    if running:
                        # 已在跑但埠沒開:open --args 對已開的 App 無效 → 先優雅關閉再重帶
                        print("[obs] OBS 在跑但 websocket 埠沒開,先關閉重帶")
                        subprocess.run(["osascript", "-e", 'quit app "OBS"'], capture_output=True)
                        for _ in range(20):
                            time.sleep(0.5)
                            if subprocess.run(["pgrep", "-x", "OBS"], capture_output=True).returncode != 0:
                                break
                        running = subprocess.run(["pgrep", "-x", "OBS"], capture_output=True).returncode == 0
                        if running:
                            subprocess.run(["pkill", "-9", "-x", "OBS"], capture_output=True); time.sleep(1)
                            running = False
                    # 不靠參數:寫入 obs-websocket 設定(OBS 沒在跑時寫才不會被覆蓋)
                    try:
                        cfgd = os.path.expanduser("~/Library/Application Support/obs-studio/plugin_config/obs-websocket")
                        os.makedirs(cfgd, exist_ok=True)
                        with open(os.path.join(cfgd, "config.json"), "w", encoding="utf-8") as _f:
                            json.dump({"alerts_enabled": False, "auth_required": True, "first_load": False,
                                       "server_enabled": True, "server_password": self.password,
                                       "server_port": self.port}, _f)
                    except Exception as _e:
                        print("[obs] 寫 websocket 設定失敗: %s" % _e)
                    if not running:
                        clear_sentinel()
                        app = "/Applications/OBS.app"
                        if not os.path.isdir(app):
                            app = os.path.expanduser("~/Applications/OBS.app")
                        subprocess.Popen(["open", "-a", app, "--args",
                                          "--profile", "Prime Stage 直式", "--collection", "Prime Stage 直式",
                                          "--minimize-to-tray", "--disable-shutdown-check",
                                          "--websocket_port", str(self.port),
                                          "--websocket_password", self.password])
                        print("[obs] 引擎自行啟動 OBS(帶 websocket 參數)")
                elif sys.platform == "win32":
                    running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe"], capture_output=True, text=True).stdout.find("obs64.exe") >= 0
                    if running:
                        # 活著但埠沒開(多半卡在「不乾淨關閉」對話框):關掉重帶
                        print("[obs] OBS 在跑但 websocket 埠沒開,先關閉重帶")
                        subprocess.run(["taskkill", "/IM", "obs64.exe", "/F"], capture_output=True, creationflags=0x08000000)
                        time.sleep(2); running = False
                    if not running:
                        clear_sentinel()
                        for exe in (r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",):
                            if os.path.exists(exe):
                                subprocess.Popen([exe, "--profile", "Prime Stage 直式", "--collection", "Prime Stage 直式",
                                                  "--minimize-to-tray", "--disable-shutdown-check",
                                                  "--websocket_port", str(self.port),
                                                  "--websocket_password", self.password], cwd=os.path.dirname(exe))
                                print("[obs] 引擎自行啟動 OBS(帶 websocket 參數)")
                                break
                for _ in range(90):
                    time.sleep(1)
                    if port_open():
                        self.connected = True
                        print("[obs] websocket 已連通")
                        return
                # 診斷
                self.connected = False
                print("[obs] 90 秒內 websocket 埠 %d 未開。" % self.port)
                if sys.platform == "darwin":
                    alive = subprocess.run(["pgrep", "-x", "OBS"], capture_output=True).returncode == 0
                    print("[obs] OBS 程序活著=%s" % alive)
                    self.diag = ("OBS 沒有啟動" if not alive else "OBS 已開但遙控埠沒開")
                    logs = sorted(glob.glob(os.path.expanduser("~/Library/Application Support/obs-studio/logs/*.txt")))
                    if logs:
                        try:
                            tail = open(logs[-1], encoding="utf-8", errors="ignore").read().splitlines()[-40:]
                            print("[obs] OBS log 尾(%s):" % os.path.basename(logs[-1]))
                            for ln in tail:
                                if any(k in ln.lower() for k in ("websocket", "module", "plugin", "error", "fail", "load")):
                                    print("   " + ln)
                        except Exception:
                            pass
            finally:
                self._ensuring = False
        threading.Thread(target=run, daemon=True).start()

    def set_stream_key_async(self, key):
        """即時把新金鑰推給 OBS(SetStreamServiceSettings),免重開 OBS。連不上就算了(service.json 已寫,下次啟動生效)。"""
        def run():
            try:
                server = "rtmps://af36b0817398.global-contribute.live-video.net:443/app/"
                try:    # 用 service.json 現有 server(廠商換正式位址也跟著對)
                    sd = json.load(open(_obs_profile_service_path(), encoding="utf-8"))
                    server = sd.get("settings", {}).get("server", server)
                except Exception:
                    pass
                self._rpc("SetStreamServiceSettings", {
                    "streamServiceType": "rtmp_custom",
                    "streamServiceSettings": {
                        "server": server, "key": key, "use_auth": False, "bwtest": False}})
                self.connected = True
            except Exception:
                self.connected = False
        threading.Thread(target=run, daemon=True).start()

    def poll_async(self):
        if self.busy:
            return
        self.busy = True
        def run():
            try:
                d = self._rpc("GetStreamStatus")
                rd = d.get("responseData") or {}
                self.streaming = bool(rd.get("outputActive"))
                self.connected = True
            except Exception:
                self.connected = False
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()


# ---------- v7 主視窗（即時畫面+濾鏡條+開始直播;OBS 藏系統匣,主播只看這窗）----------
STRIP_VIEW_W = 1220
STRIP_TW = 78
STRIP_GAP, STRIP_PAD = 6, 12
STRIP_HDR, STRIP_TAGH, STRIP_LBL, STRIP_SBH, STRIP_FOOT = 30, 16, 27, 7, 18
_CATZH = {"basic": "美顏", "beauty": "美顏", "color": "調色", "bg": "換背景", "fun": "趣味"}
_CATEN = {"basic": "Beauty", "beauty": "Beauty", "color": "Color", "bg": "Background", "fun": "Fun"}
_C_BG = (23, 18, 16); _C_HDR = (32, 26, 22); _C_TXT = (246, 243, 240); _C_SUB = (162, 150, 139)
_C_GOLD = (122, 193, 233); _C_ACC = (96, 164, 240); _C_DIM = (116, 103, 96)   # BGR

class ThumbWorker:
    """背景執行緒:拿一格快照,把全部濾鏡各跑一次引擎管線,生成同尺寸縮圖。
    不佔主迴圈(虛擬攝影機輸出不中斷);R 鍵可用最新畫面重生。"""
    def __init__(self, presets, assets):
        self.presets = presets
        self.assets = assets
        self.thumbs = [None] * len(presets)
        self.busy = False
        self.version = 0
        self._lm = None
        self._seg = None

    def start(self, frame_bgr, tw, th, out_list=None):
        if self.busy or frame_bgr is None:
            return
        self.busy = True
        if out_list is None:
            out_list = self.thumbs
        threading.Thread(target=self._run, args=(frame_bgr.copy(), tw, th, out_list), daemon=True).start()

    def _ensure_models(self):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        if self._lm is None:
            self._lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL),
                running_mode=vision.RunningMode.IMAGE, num_faces=1))
            if os.path.exists(MODEL_SEG):
                self._seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=MODEL_SEG),
                    running_mode=vision.RunningMode.IMAGE, output_confidence_masks=True))
        return mp

    def _run(self, frame, tw, th, out_list):
        try:
            mp = self._ensure_models()
            h0, w0 = frame.shape[:2]
            rgb = cv2.cvtColor(cv2.resize(frame, (300, max(2, int(300 * h0 / w0))),
                                          interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
            H, W = rgb.shape[:2]
            res = self._lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
            lms = res.face_landmarks[0] if res.face_landmarks else None
            segm = None
            if self._seg is not None:
                small = np.ascontiguousarray(cv2.resize(rgb, (384, 216)))
                s = self._seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=small))
                if s.confidence_masks:
                    m = np.asarray(s.confidence_masks[0].numpy_view(), dtype=np.float32)
                    segm = cv2.GaussianBlur(cv2.resize(m, (W, H)), (0, 0), 3.0)[..., None]
            for i, p in enumerate(self.presets):
                out = rgb.copy()
                if p.get("background") and segm is not None:
                    bg = load_bg(os.path.join(self.assets, p["background"]), W, H)
                    if bg is not None:
                        out = (out.astype(np.float32) * segm + bg.astype(np.float32) * (1 - segm)).astype(np.uint8)
                if p.get("beauty") and lms is not None:
                    out = apply_beauty(out, lms, p["beauty"])
                if p.get("warp") and lms is not None:
                    w = p["warp"]
                    out = apply_warp(out, lms, float(w.get("eye", 0)), float(w.get("mouth", 0)))
                if p.get("lut"):
                    out = apply_lut(out, load_cube(os.path.join(self.assets, p["lut"])))
                if p.get("sticker") and lms is not None:
                    if p.get("anchor") == "head":
                        cx, cy, twd, ang = head_placement(lms, W, H, p.get("scale", 2.2), p.get("y_off", -0.15))
                    else:
                        cx, cy, twd, ang = crown_placement(lms, W, H)
                    out = overlay(out, load_sticker(os.path.join(self.assets, p["sticker"])), cx, cy, twd, ang)
                out_list[i] = cv2.resize(cv2.cvtColor(out, cv2.COLOR_RGB2BGR), (tw, th),
                                         interpolation=cv2.INTER_AREA)
                self.version += 1
        except Exception as e:
            print("[note] 縮圖產生失敗: %s %s" % (type(e).__name__, e))
        finally:
            self.busy = False


DEMO_CHIP = (STRIP_VIEW_W - 318, 4, STRIP_VIEW_W - 246, STRIP_HDR - 4)   # 右上「示範:女/男」點擊區

def build_strip_view(presets, thumbs, active, scroll, tw, th, status, demo_label=""):
    """畫單排選擇器視圖(可捲動視窗)。回傳 (BGR, 命中矩形, max_scroll, 視窗高)。"""
    n = len(presets)
    content_w = STRIP_PAD * 2 + n * tw + (n - 1) * STRIP_GAP
    max_scroll = max(0, content_w - STRIP_VIEW_W)
    scroll = int(max(0, min(scroll, max_scroll)))
    H = STRIP_HDR + STRIP_TAGH + th + STRIP_LBL + 2 + STRIP_SBH + 4 + STRIP_FOOT

    pil = PILImage.new("RGB", (STRIP_VIEW_W, H), (_C_BG[2], _C_BG[1], _C_BG[0]))
    d = PILDraw.Draw(pil, "RGBA")
    zhb = lambda s: _uifont("zhb", s); zh = lambda s: _uifont("zh", s)
    en = lambda s: _uifont("en", s); ensb = lambda s: _uifont("ensb", s)
    GOLD = (233, 193, 122); ACCENT = (240, 164, 96); TXT = (240, 242, 246)
    SUB = (139, 147, 162); DIM = (96, 102, 116)

    # 頂欄
    d.rectangle([0, 0, STRIP_VIEW_W, STRIP_HDR], fill=(22, 25, 32))
    d.text((STRIP_PAD, 5), "primelive", font=ensb(13), fill=GOLD)
    plw = d.textlength("primelive", font=ensb(13))
    d.text((STRIP_PAD + plw + 8, 7), "一鍵濾鏡", font=zhb(10), fill=TXT)
    cur = presets[active]
    d.text((STRIP_VIEW_W / 2, STRIP_HDR / 2), "目前 %s · %s" % (cur.get("name", ""), cur.get("en", "")),
           font=zh(10), fill=(250, 214, 166), anchor="mm")
    d.text((STRIP_VIEW_W - STRIP_PAD, STRIP_HDR / 2), status, font=en(9), fill=SUB, anchor="rm")
    if demo_label:
        d.rounded_rectangle(list(DEMO_CHIP), radius=10, outline=(120, 127, 142), width=1)
        d.text(((DEMO_CHIP[0] + DEMO_CHIP[2]) / 2, STRIP_HDR / 2), demo_label, font=zh(9),
               fill=(250, 214, 166), anchor="mm")

    ty = STRIP_HDR + STRIP_TAGH
    rects = []
    prev_cat = None
    for i, p in enumerate(presets):
        x = STRIP_PAD + i * (tw + STRIP_GAP) - scroll
        cat = _CATZH.get(p.get("cat", "basic"), "")
        if cat != prev_cat:
            if -120 < x < STRIP_VIEW_W:
                d.text((max(2, x), STRIP_HDR + 1),
                       "%s  %s" % (cat, _CATEN.get(p.get("cat", "basic"), "")),
                       font=zhb(8.5), fill=GOLD if cat == "美顏" else SUB)
            prev_cat = cat
        if x + tw < 0 or x > STRIP_VIEW_W:
            continue
        on = (i == active)
        tb = thumbs[i]
        if tb is not None:
            pil.paste(PILImage.fromarray(cv2.cvtColor(tb, cv2.COLOR_BGR2RGB)), (int(x), ty))
        else:
            d.rounded_rectangle([x, ty, x + tw, ty + th], radius=6, fill=(30, 33, 41))
            d.text((x + tw / 2, ty + th / 2), "更新中", font=zh(8), fill=DIM, anchor="mm")
        if on:
            d.rounded_rectangle([x, ty, x + tw, ty + th], radius=6, outline=ACCENT, width=2)
        d.text((x + tw / 2, ty + th + 2), p.get("name", ""), font=zhb(9) if on else zh(9),
               fill=(250, 214, 166) if on else TXT, anchor="ma")
        enl = p.get("en", "")
        if d.textlength(enl, font=en(6.5)) > tw:
            enl = enl[:13] + "…"
        d.text((x + tw / 2, ty + th + 15), enl, font=en(6.5), fill=SUB, anchor="ma")
        rects.append((int(x), ty, int(x + tw), ty + th, i))

    # 邊緣淡出+箭頭
    if scroll > 0:
        d.polygon([(10, ty + th / 2 - 8), (4, ty + th / 2), (10, ty + th / 2 + 8)], fill=(210, 214, 222))
    if scroll < max_scroll:
        d.polygon([(STRIP_VIEW_W - 10, ty + th / 2 - 8), (STRIP_VIEW_W - 4, ty + th / 2),
                   (STRIP_VIEW_W - 10, ty + th / 2 + 8)], fill=(210, 214, 222))

    # 捲動條
    sy = ty + th + STRIP_LBL + 2
    d.rounded_rectangle([STRIP_PAD, sy, STRIP_VIEW_W - STRIP_PAD, sy + STRIP_SBH - 2], radius=2, fill=(34, 38, 47))
    frac = min(1.0, STRIP_VIEW_W / float(content_w))
    bar_w = (STRIP_VIEW_W - STRIP_PAD * 2) * frac
    bar_x = STRIP_PAD + (STRIP_VIEW_W - STRIP_PAD * 2 - bar_w) * (scroll / float(max_scroll) if max_scroll else 0)
    d.rounded_rectangle([bar_x, sy, bar_x + bar_w, sy + STRIP_SBH - 2], radius=2, fill=(88, 95, 110))

    fy = H - STRIP_FOOT - 1
    d.text((STRIP_PAD, fy), "左右滑動或 ← → 換濾鏡 · 點縮圖直接選 · 右上可切換示範模特(女/男)",
           font=zh(8.2), fill=SUB)
    bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return bgr, rects, max_scroll, H


# 直播固定直式:攝影機一進管線就中央裁成 OBS 畫布比例(720:1920)。
# 之後預覽/虛擬攝影機/OBS 全鏈路只有直式,且處理像素變少(防lag加分)。
CANVAS_AR = 720.0 / 1280.0

def crop_portrait(frame):
    if frame is None:
        return frame
    h, w = frame.shape[:2]
    tw_ = int(h * CANVAS_AR) // 2 * 2
    if 2 <= tw_ < w:
        x0 = (w - tw_) // 2
        return np.ascontiguousarray(frame[:, x0:x0 + tw_])
    th_ = int(w / CANVAS_AR) // 2 * 2
    if 2 <= th_ < h:
        y0 = (h - th_) // 2
        return np.ascontiguousarray(frame[y0:y0 + th_, :])
    return frame

PV_H = 440
PV_W = int(PV_H * CANVAS_AR) // 2 * 2      # ≈202,直式手機比例
LIVE_BTN = (STRIP_VIEW_W - 228, STRIP_HDR + 168, STRIP_VIEW_W - 28, STRIP_HDR + 236)

def build_main_view(presets, thumbs, active, scroll, tw, th, live, demo_label):
    """v7 主視窗:header + 即時畫面(中央) + 左資訊/右開播鈕 + 濾鏡條 + footer。
    回傳 (BGR, rects, max_scroll, H, preview_slot)。preview 由主迴圈每格貼上。"""
    n = len(presets)
    content_w = STRIP_PAD * 2 + n * tw + (n - 1) * STRIP_GAP
    max_scroll = max(0, content_w - STRIP_VIEW_W)
    scroll = int(max(0, min(scroll, max_scroll)))
    pv_y = STRIP_HDR + 8
    strip_y = pv_y + PV_H + 10
    ty = strip_y + STRIP_TAGH
    H = ty + th + STRIP_LBL + 2 + STRIP_SBH + 4 + STRIP_FOOT

    pil = PILImage.new("RGB", (STRIP_VIEW_W, H), (23, 18, 16))
    d = PILDraw.Draw(pil, "RGBA")
    zhb = lambda s: _uifont("zhb", s); zh = lambda s: _uifont("zh", s)
    en = lambda s: _uifont("en", s); ensb = lambda s: _uifont("ensb", s)
    GOLD = (233, 193, 122); ACCENT = (240, 164, 96); TXT = (240, 242, 246)
    SUB = (139, 147, 162); DIM = (96, 102, 116)

    # 頂欄
    d.rectangle([0, 0, STRIP_VIEW_W, STRIP_HDR], fill=(22, 25, 32))
    d.text((STRIP_PAD, 6), "primelive", font=ensb(14), fill=GOLD)
    plw = d.textlength("primelive", font=ensb(14))
    d.text((STRIP_PAD + plw + 8, 9), "一鍵直播", font=zhb(11), fill=TXT)
    if demo_label:
        d.rounded_rectangle(list(DEMO_CHIP), radius=10, outline=(120, 127, 142), width=1)
        d.text(((DEMO_CHIP[0] + DEMO_CHIP[2]) / 2, STRIP_HDR / 2), demo_label, font=zh(9),
               fill=(250, 214, 166), anchor="mm")

    # 即時畫面框(置中) — 內容由主迴圈每格貼
    pv_x = (STRIP_VIEW_W - PV_W) // 2
    d.rounded_rectangle([pv_x - 2, pv_y - 2, pv_x + PV_W + 2, pv_y + PV_H + 2],
                        radius=8, outline=(58, 63, 76), width=1, fill=(12, 13, 17))
    d.text((pv_x + PV_W / 2, pv_y + PV_H / 2), "等待攝影機…", font=zh(12), fill=DIM, anchor="mm")

    # 左資訊欄
    cur = presets[active]
    lx = STRIP_PAD + 8
    d.text((lx, pv_y + 16), "目前濾鏡", font=zh(10), fill=SUB)
    d.text((lx, pv_y + 36), cur.get("name", ""), font=zhb(19), fill=(250, 214, 166))
    d.text((lx, pv_y + 68), cur.get("en", ""), font=en(11), fill=SUB)
    d.text((lx, pv_y + 110), "畫面已含濾鏡效果", font=zh(9.5), fill=SUB)
    d.text((lx, pv_y + 128), "＝觀眾看到的樣子", font=zh(9.5), fill=SUB)

    # 右欄:開始直播大鈕 + 狀態
    bx0, by0, bx1, by1 = LIVE_BTN
    if live.get("busy"):
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=12, fill=(70, 74, 86))
        d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), "處理中…", font=zhb(15), fill=(210, 213, 220), anchor="mm")
    elif live.get("streaming"):
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=12, fill=(64, 68, 80), outline=(120, 127, 142), width=1)
        d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), "■  停止直播", font=zhb(16), fill=(255, 176, 168), anchor="mm")
    else:
        d.rounded_rectangle([bx0, by0, bx1, by1], radius=12, fill=(204, 62, 54))
        d.text(((bx0 + bx1) / 2, (by0 + by1) / 2), "●  開始直播", font=zhb(16), fill=(255, 245, 242), anchor="mm")
    if live.get("streaming"):
        st = "直播中 · 平台記得按「確認開播」"
        stc = (255, 176, 168)
    elif live.get("connected"):
        st = "OBS 已就緒(背景執行)"
        stc = (150, 220, 170)
    else:
        st = "等待 OBS 連線…"
        stc = SUB
    d.text(((bx0 + bx1) / 2, by1 + 18), st, font=zh(9.5), fill=stc, anchor="mm")
    d.text(((bx0 + bx1) / 2, by0 - 16), "不用開 OBS,按這顆就好", font=zh(9.5), fill=SUB, anchor="mm")

    # 濾鏡條
    rects = []
    prev_cat = None
    for i, p in enumerate(presets):
        x = STRIP_PAD + i * (tw + STRIP_GAP) - scroll
        cat = _CATZH.get(p.get("cat", "basic"), "")
        if cat != prev_cat:
            if -120 < x < STRIP_VIEW_W:
                d.text((max(2, x), strip_y + 1), "%s  %s" % (cat, _CATEN.get(p.get("cat", "basic"), "")),
                       font=zhb(8.5), fill=GOLD if cat == "美顏" else SUB)
            prev_cat = cat
        if x + tw < 0 or x > STRIP_VIEW_W:
            continue
        on = (i == active)
        tb = thumbs[i]
        if tb is not None:
            pil.paste(PILImage.fromarray(cv2.cvtColor(tb, cv2.COLOR_BGR2RGB)), (int(x), ty))
        else:
            d.rounded_rectangle([x, ty, x + tw, ty + th], radius=6, fill=(30, 33, 41))
            d.text((x + tw / 2, ty + th / 2), "更新中", font=zh(8), fill=DIM, anchor="mm")
        if on:
            d.rounded_rectangle([x, ty, x + tw, ty + th], radius=6, outline=ACCENT, width=2)
        d.text((x + tw / 2, ty + th + 2), p.get("name", ""), font=zhb(9) if on else zh(9),
               fill=(250, 214, 166) if on else TXT, anchor="ma")
        enl = p.get("en", "")
        if d.textlength(enl, font=en(6.5)) > tw:
            enl = enl[:13] + "…"
        d.text((x + tw / 2, ty + th + 15), enl, font=en(6.5), fill=SUB, anchor="ma")
        rects.append((int(x), ty, int(x + tw), ty + th, i))

    if scroll > 0:
        d.polygon([(10, ty + th / 2 - 8), (4, ty + th / 2), (10, ty + th / 2 + 8)], fill=(210, 214, 222))
    if scroll < max_scroll:
        d.polygon([(STRIP_VIEW_W - 10, ty + th / 2 - 8), (STRIP_VIEW_W - 4, ty + th / 2),
                   (STRIP_VIEW_W - 10, ty + th / 2 + 8)], fill=(210, 214, 222))
    sy = ty + th + STRIP_LBL + 2
    d.rounded_rectangle([STRIP_PAD, sy, STRIP_VIEW_W - STRIP_PAD, sy + STRIP_SBH - 2], radius=2, fill=(34, 38, 47))
    frac = min(1.0, STRIP_VIEW_W / float(content_w))
    bar_w = (STRIP_VIEW_W - STRIP_PAD * 2) * frac
    bar_x = STRIP_PAD + (STRIP_VIEW_W - STRIP_PAD * 2 - bar_w) * (scroll / float(max_scroll) if max_scroll else 0)
    d.rounded_rectangle([bar_x, sy, bar_x + bar_w, sy + STRIP_SBH - 2], radius=2, fill=(88, 95, 110))
    d.text((STRIP_PAD, H - STRIP_FOOT - 1),
           "左右滑動或 ← → 換濾鏡 · 點縮圖直接選 · 右上切換示範模特 · 準備好按「開始直播」",
           font=zh(8.2), fill=SUB)

    bgr = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return bgr, rects, max_scroll, H, (pv_x, pv_y, PV_W, PV_H)


# ---------- v8 手機式直式視窗:影像全幅+半透明浮層(自動隱藏濾鏡盤) ----------
WIN_H = 940
WIN_W = int(WIN_H * CANVAS_AR) // 2 * 2    # ≈432,整窗就是直式畫面(設計基準尺寸)
TRAY_TW = 76                                # 濾鏡盤縮圖寬

def _screen_h():
    """主螢幕實體高度(px);高 DPI 螢幕上 OpenCV 視窗不吃系統縮放,要自己放大。"""
    try:
        if sys.platform == "win32":
            import ctypes
            try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception: pass
            return int(ctypes.windll.user32.GetSystemMetrics(1))
        if sys.platform == "darwin":
            import subprocess, re
            out = subprocess.run(["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=8).stdout
            m = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", out)
            if m: return int(m.group(2))
    except Exception:
        pass
    return 1080

# 顯示倍率:讓視窗高≈螢幕高 85%;1080p≈1.0,4K≈2.0。UI 一律以基準尺寸繪製再整張放大,滑鼠座標除回來。
UI_SCALE = max(1.0, round((_screen_h() * 0.85) / float(WIN_H), 2))
DISP_W, DISP_H = int(WIN_W * UI_SCALE) // 2 * 2, int(WIN_H * UI_SCALE) // 2 * 2

def _alpha_paste(dst_bgr, ov_rgba, x, y):
    """把 RGBA 浮層(含半透明)貼到 BGR 畫面上。"""
    h, w = ov_rgba.shape[:2]
    x = int(x); y = int(y)
    if x >= dst_bgr.shape[1] or y >= dst_bgr.shape[0]:
        return
    w = min(w, dst_bgr.shape[1] - x); h = min(h, dst_bgr.shape[0] - y)
    roi = dst_bgr[y:y + h, x:x + w].astype(np.float32)
    ov = ov_rgba[:h, :w].astype(np.float32)
    a = ov[..., 3:4] / 255.0
    dst_bgr[y:y + h, x:x + w] = (roi * (1 - a) + ov[..., 2::-1] * a).astype(np.uint8)

def _rgba(pil_img):
    return np.array(pil_img.convert("RGBA"))

def build_topbar(cur, demo_label, live):
    """頂部半透明資訊列:品牌+目前濾鏡+示範chip+直播狀態。"""
    H = 74
    im = PILImage.new("RGBA", (WIN_W, H), (10, 10, 14, 185))
    d = PILDraw.Draw(im)
    zhb = lambda s: _uifont("zhb", s); zh = lambda s: _uifont("zh", s); ensb = lambda s: _uifont("ensb", s)
    d.text((12, 6), "primelive", font=ensb(16), fill=(233, 193, 122, 255))
    d.text((12, 32), "目前濾鏡：" + cur.get("name", ""), font=zhb(19), fill=(255, 255, 255, 255))
    # 右上角 ✕ 關閉(mac 的系統關閉鈕不會通知 OpenCV 視窗,自畫一顆)
    d.rounded_rectangle([WIN_W - 38, 6, WIN_W - 8, 32], radius=8, fill=(255, 255, 255, 50))
    d.line([WIN_W - 30, 12, WIN_W - 16, 26], fill=(240, 242, 246, 255), width=3)
    d.line([WIN_W - 16, 12, WIN_W - 30, 26], fill=(240, 242, 246, 255), width=3)
    # 設定鈕(切換鏡頭/換金鑰);自畫齒輪圖示避免字型缺 emoji
    d.rounded_rectangle([WIN_W - 120, 6, WIN_W - 46, 30], radius=12, fill=(255, 255, 255, 45))
    gx, gy = WIN_W - 108, 18
    d.ellipse([gx - 6, gy - 6, gx + 6, gy + 6], outline=(245, 246, 250, 255), width=2)
    d.ellipse([gx - 2, gy - 2, gx + 2, gy + 2], fill=(245, 246, 250, 255))
    d.text((WIN_W - 74, 18), "設定", font=zhb(14), fill=(245, 246, 250, 255), anchor="mm")
    if live.get("streaming"):
        d.ellipse([WIN_W - 158, 12, WIN_W - 148, 22], fill=(235, 70, 60, 255))
        d.text((WIN_W - 164, 8), "LIVE", font=ensb(12), fill=(255, 120, 110, 255), anchor="ra")
    if demo_label:
        d.rounded_rectangle([WIN_W - 150, 34, WIN_W - 10, 66], radius=16, fill=(255, 255, 255, 60))
        d.text((WIN_W - 80, 50), demo_label, font=zhb(14), fill=(255, 245, 230, 255), anchor="mm")
    return _rgba(im)

def _obs_profile_service_path():
    base = (os.environ.get("APPDATA", "") if sys.platform == "win32"
            else os.path.expanduser("~/Library/Application Support"))
    return os.path.join(base, "obs-studio", "basic", "profiles", "Prime Stage 直式", "service.json")

def _prompt_key():
    """跳原生輸入框問金鑰(Win=PowerShell InputBox,mac=osascript);回傳去空白後字串或 ''。"""
    try:
        import subprocess
        if sys.platform == "win32":
            ps = ('Add-Type -AssemblyName Microsoft.VisualBasic;'
                  '[Microsoft.VisualBasic.Interaction]::InputBox('
                  '"請貼上新的直播金鑰`n(直播主後台 → 設定 → OBS平台金鑰 → 複製)","primelive 換金鑰","")')
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=120)
            return (out.stdout or "").strip()
        if sys.platform == "darwin":
            scr = ('text returned of (display dialog "請貼上新的直播金鑰\\n(直播主後台 → 設定 → OBS平台金鑰 → 複製)"'
                   ' default answer "" with title "primelive 換金鑰")')
            out = subprocess.run(["osascript", "-e", scr], capture_output=True, text=True, timeout=120)
            return (out.stdout or "").strip()
    except Exception:
        pass
    return ""

def _write_stream_key(key):
    """把金鑰寫進 OBS profile 的 service.json(保留其餘設定)。"""
    try:
        p = _obs_profile_service_path()
        d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"type": "rtmp_custom", "settings": {}}
        d.setdefault("settings", {})["key"] = key
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        return True
    except Exception as e:
        print("[key] 寫入失敗: %s" % e)
        return False

def build_settings_panel(cam_name):
    """設定選單:切換鏡頭 / 換金鑰。回傳 (RGBA, {item:rect(相對面板)}, 面板位置(x,y))。"""
    PW_, PH_ = WIN_W - 60, 232
    px, py = 30, 180
    im = PILImage.new("RGBA", (PW_, PH_), (0, 0, 0, 0))
    d = PILDraw.Draw(im)
    d.rounded_rectangle([0, 0, PW_ - 1, PH_ - 1], radius=18, fill=(24, 24, 32, 245), outline=(80, 84, 96, 255), width=2)
    zhb = lambda s: _uifont("zhb", s); zh = lambda s: _uifont("zh", s)
    d.text((PW_ // 2, 24), "設定", font=zhb(18), fill=(240, 200, 120, 255), anchor="mm")
    rects = {}
    # 切換鏡頭
    d.rounded_rectangle([20, 52, PW_ - 20, 104], radius=12, fill=(58, 62, 74, 255))
    d.text((PW_ // 2, 70), "切換鏡頭", font=zhb(16), fill=(255, 255, 255, 255), anchor="mm")
    d.text((PW_ // 2, 90), "目前：" + (cam_name or "—"), font=zh(11), fill=(190, 195, 205, 255), anchor="mm")
    rects["cam"] = (20, 52, PW_ - 20, 104)
    # 換金鑰
    d.rounded_rectangle([20, 116, PW_ - 20, 156], radius=12, fill=(58, 62, 74, 255))
    d.text((PW_ // 2, 136), "換直播金鑰", font=zhb(16), fill=(255, 255, 255, 255), anchor="mm")
    rects["key"] = (20, 116, PW_ - 20, 156)
    # 關閉
    d.rounded_rectangle([20, 172, PW_ - 20, 210], radius=12, fill=(44, 46, 56, 255))
    d.text((PW_ // 2, 191), "關閉", font=zhb(15), fill=(220, 222, 228, 255), anchor="mm")
    rects["close"] = (20, 172, PW_ - 20, 210)
    return _rgba(im), rects, (px, py)

def build_tray(presets, thumbs, active, scroll, tw, th):
    """底部半透明濾鏡盤(可捲動);回傳 (RGBA, 局部命中矩形, max_scroll, 高)。"""
    PAD = 10; GAP = 8; LBL = 34
    H = 12 + th + LBL
    n = len(presets)
    content_w = PAD * 2 + n * tw + (n - 1) * GAP
    max_scroll = max(0, content_w - WIN_W)
    scroll = int(max(0, min(scroll, max_scroll)))
    im = PILImage.new("RGBA", (WIN_W, H), (0, 0, 0, 0))
    d = PILDraw.Draw(im)
    d.rounded_rectangle([0, 0, WIN_W, H + 14], radius=14, fill=(12, 12, 18, 165))
    zhb = lambda s: _uifont("zhb", s); zh = lambda s: _uifont("zh", s)
    rects = []
    ty = 8
    for i, p in enumerate(presets):
        x = PAD + i * (tw + GAP) - scroll
        if x + tw < 0 or x > WIN_W:
            continue
        on = (i == active)
        tb = thumbs[i]
        if tb is not None:
            t = PILImage.fromarray(cv2.cvtColor(cv2.resize(tb, (tw, th)), cv2.COLOR_BGR2RGB)).convert("RGBA")
            mask = PILImage.new("L", (tw, th), 0)
            PILDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1], radius=8, fill=255)
            t.putalpha(mask)
            im.paste(t, (int(x), ty), t)
        else:
            d.rounded_rectangle([x, ty, x + tw, ty + th], radius=8, fill=(38, 40, 50, 200))
        if on:
            d.rounded_rectangle([x - 1, ty - 1, x + tw + 1, ty + th + 1], radius=9,
                                outline=(240, 164, 96, 255), width=2)
        nm = p.get("name", "")
        d.text((x + tw / 2, ty + th + 4), nm, font=zhb(14) if on else zh(14),
               fill=(255, 220, 170, 255) if on else (245, 246, 250, 240), anchor="ma")
        rects.append((int(x), ty, int(x + tw), ty + th, i))
    return _rgba(im), rects, max_scroll, H

def build_livebtn(live):
    """浮動「開始直播」膠囊鈕(半透明)。"""
    W, H = 300, 72
    im = PILImage.new("RGBA", (W, H), (0, 0, 0, 0))
    d = PILDraw.Draw(im)
    zhb = lambda s: _uifont("zhb", s)
    if live.get("busy"):
        d.rounded_rectangle([0, 0, W, H], radius=36, fill=(58, 62, 74, 240), outline=(200, 205, 215, 230), width=2)
        d.text((W / 2, H / 2), "準備 OBS 中…" if not live.get("connected") else "處理中…",
               font=zhb(22), fill=(255, 255, 255, 255), anchor="mm")
    elif live.get("streaming"):
        d.rounded_rectangle([0, 0, W, H], radius=36, fill=(40, 42, 52, 235), outline=(220, 225, 235, 230), width=2)
        d.text((W / 2, H / 2), "■ 停止直播", font=zhb(23), fill=(255, 200, 190, 255), anchor="mm")
    else:
        d.rounded_rectangle([0, 0, W, H], radius=36, fill=(216, 56, 48, 245))
        d.text((W / 2, H / 2), "● 開始直播", font=zhb(23), fill=(255, 255, 255, 255), anchor="mm")
    return _rgba(im)

def build_handle():
    """濾鏡盤收起後的喚醒把手。"""
    W, H = 130, 32
    im = PILImage.new("RGBA", (W, H), (0, 0, 0, 0))
    d = PILDraw.Draw(im)
    d.rounded_rectangle([0, 0, W, H], radius=16, fill=(12, 12, 18, 180))
    d.text((W / 2, H / 2), "︿ 濾鏡", font=_uifont("zhb", 14), fill=(245, 247, 250, 245), anchor="mm")
    return _rgba(im)


# ---------- 鏡頭選擇（用名稱挑 OBSBOT，永不誤開手機/連線相機）----------
# 索引會隨插拔位移(OBSBOT 曾是 3、後來變 0)，所以改用「名稱」選鏡頭最穩。
_PHONE_PAT = ("連線相機", "虛擬攝影機", "phone", "手機", "galaxy", "s26", "s25", "s24",
              "droidcam", "iriun", "camo", "epoccam", "ivcam", "link to windows")
_PREFER_PAT = ("obsbot tiny",)   # 真實 OBSBOT 實體鏡頭(不是 OBSBOT Virtual)

CAP_BACKEND = cv2.CAP_DSHOW if sys.platform == "win32" else (
    cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY)

def list_camera_names():
    """鏡頭名稱清單(Windows=DirectShow 與 cv2 索引一致;macOS=system_profiler 盡力對應)。
    取不到回 None。只列名、不開鏡頭。"""
    if sys.platform == "win32":
        try:
            from pygrabber.dshow_graph import FilterGraph
            return list(FilterGraph().get_input_devices())
        except Exception:
            return None
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(["system_profiler", "SPCameraDataType", "-json"],
                                 capture_output=True, timeout=10)
            data = json.loads(out.stdout.decode("utf-8", "ignore"))
            names = [c.get("_name", "") for c in data.get("SPCameraDataType", [])]
            return names or None
        except Exception:
            return None
    return None

def _is_phone(name):
    n = (name or "").lower()
    return any(p in n for p in _PHONE_PAT)

def pick_camera_index(names, prefer=None, allow_phone=False):
    """依名稱挑鏡頭：①指定關鍵字 ②OBSBOT 實體 ③第一個非手機非虛擬 ④第一個非手機 ⑤(允許時)手機。
    回傳 (index, name)；無法判斷回 (None, None)。"""
    if not names:
        return None, None
    if prefer:
        for i, n in enumerate(names):
            if prefer.lower() in n.lower() and (allow_phone or not _is_phone(n)):
                return i, n
    for i, n in enumerate(names):
        if any(p in n.lower() for p in _PREFER_PAT):
            return i, n
    for i, n in enumerate(names):
        if not _is_phone(n) and "virtual" not in n.lower():
            return i, n
    for i, n in enumerate(names):
        if not _is_phone(n):
            return i, n
    if allow_phone:           # 都沒有(只剩手機) → 允許時就用手機
        for i, n in enumerate(names):
            if _is_phone(n):
                return i, n
    return None, None


# ---------- 防 lag：背景抓圖執行緒 + 自動調解析度 ----------

class CameraThread:
    """背景執行緒持續抓「最新一格」。主迴圈不再被相機 I/O 卡住，也不會累積延遲
    （慢的時候直接丟掉舊格、永遠處理最新的）。可用 swap() 換相機。"""
    def __init__(self, cap):
        self.cap = cap
        self.lock = threading.Lock()
        self.frame = None
        self.seq = 0            # 每抓到新一格 +1，主迴圈用來判斷是不是新的
        self.running = True
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def _loop(self):
        while self.running:
            cap = self.cap
            ok, fr = (cap.read() if cap is not None else (False, None))
            if not ok or fr is None:
                time.sleep(0.005)
                continue
            with self.lock:
                self.frame = fr
                self.seq += 1

    def read(self):
        """回傳 (有沒有畫面, frame, seq)。seq 沒變＝還是同一格。"""
        with self.lock:
            return (self.frame is not None), self.frame, self.seq

    def swap(self, newcap):
        old = self.cap
        with self.lock:
            self.cap = newcap
            self.frame = None
        if old is not None:
            try:
                old.release()
            except Exception:
                pass

    def stop(self):
        self.running = False
        try:
            self.th.join(timeout=0.5)
        except Exception:
            pass
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass


class Adaptive:
    """依每格「處理耗時」自動調處理解析度倍率：跟不上 fps 就降（更順），
    很有餘裕就升回去（更清晰）。強機維持 1.0＝原畫質；弱機自動降到 min_scale。"""
    def __init__(self, target_fps=30, min_scale=0.5, enabled=True):
        self.enabled = enabled
        self.budget = 1.0 / max(1, target_fps)
        self.scale = 1.0
        self.min_scale = float(min_scale)
        self.ema = self.budget
        self.cool = 0

    def update(self, dt):
        self.ema = self.ema * 0.8 + dt * 0.2          # 平滑每格耗時
        if not self.enabled or self.cool > 0:
            self.cool = max(0, self.cool - 1)
            return self.scale
        if self.ema > self.budget * 0.95 and self.scale > self.min_scale:
            self.scale = max(self.min_scale, round(self.scale - 0.1, 2))
            self.cool = 12                            # 降完等幾格再評估，避免抖動
        elif self.ema < self.budget * 0.55 and self.scale < 1.0:
            self.scale = min(1.0, round(self.scale + 0.1, 2))
            self.cool = 20
        return self.scale

    def proc_size(self, w, h):
        if self.scale >= 0.999:
            return w, h
        return (max(2, int(w * self.scale) // 2 * 2),
                max(2, int(h * self.scale) // 2 * 2))


# ---------- 主程式 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=-1, help="指定鏡頭索引；預設 -1=依名稱自動選 OBSBOT")
    ap.add_argument("--camera-name", default="OBSBOT Tiny", help="自動選鏡頭時優先比對的名稱關鍵字")
    ap.add_argument("--allow-phone", action="store_true", help="允許使用手機/連線相機(預設一律跳過手機)")
    ap.add_argument("--list-cameras", action="store_true", help="列出所有鏡頭名稱後結束(不開鏡頭)")
    ap.add_argument("--frames", type=int, default=0, help="只跑 N 格就結束(煙霧測試)")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--preset", type=int, default=0, help="起始濾鏡索引(0-based)")
    ap.add_argument("--seg-every", type=int, default=3, help="每幾格重算一次換背景遮罩")
    ap.add_argument("--cap-width", type=int, default=1280, help="擷取寬(降到 960 可衝 fps)")
    ap.add_argument("--cap-height", type=int, default=720)
    ap.add_argument("--fast", action="store_true", help="快速模式：540p 換更高 fps")
    ap.add_argument("--target-fps", type=int, default=30, help="目標 fps（自動調解析度以維持它）")
    ap.add_argument("--min-scale", type=float, default=0.5, help="自動降解析度的下限倍率（0.5＝最低降到一半）")
    ap.add_argument("--no-adaptive", action="store_true", help="關閉自動調解析度（維持固定畫質）")
    ap.add_argument("--no-threaded", action="store_true", help="關閉背景抓圖執行緒（除錯用）")
    ap.add_argument("--gpu", action="store_true", help="嘗試用 GPU 跑 MediaPipe（失敗自動退回 CPU）")
    ap.add_argument("--ready-file", default="", help="虛擬攝影機啟動後寫一個旗標檔（給一鍵開播腳本判斷可以開 OBS 了）")
    ap.add_argument("--fake-camera", action="store_true",
                    help="測試用:沒有實體鏡頭時,用內建示範圖當攝影機來源(CI 驗證整條管線)")
    ap.add_argument("--obs-vcam-kick", action="store_true",
                    help="macOS 首次自動化:遙控 OBS 啟動→停止虛擬相機以註冊系統擴充,完成即退出")
    args = ap.parse_args()

    if args.obs_vcam_kick:
        # 讓 OBS 自己註冊虛擬相機擴充(啟動→停止,註冊會永久保留);先確保 OBS 帶 websocket 起來
        ctl = ObsControl()
        ctl.ensure_obs_async()
        for _ in range(95):
            if ctl.connected:
                break
            time.sleep(1)
        ok = False
        for _ in range(30):
            try:
                ctl._rpc("StartVirtualCam")
                time.sleep(2)
                try:
                    ctl._rpc("StopVirtualCam")
                except Exception:
                    pass
                ok = True
                break
            except Exception:
                time.sleep(1)
        print("[ok] OBS 虛擬相機擴充已啟用" if ok else "[note] 連不上 OBS,略過虛擬相機啟用")
        sys.exit(0 if ok else 1)
    if args.fast:
        args.cap_width, args.cap_height = 960, 540

    if args.list_cameras:
        names = list_camera_names()
        if names is None:
            print("[note] 無法列舉鏡頭名稱(缺 pygrabber)。安裝：pip install pygrabber")
        else:
            print("=== 鏡頭清單(索引與 --camera 一致) ===")
            for i, n in enumerate(names):
                print("   %d: %s%s" % (i, n, "   <- 手機/連線相機，會自動略過" if _is_phone(n) else ""))
            idx, nm = pick_camera_index(names, args.camera_name, allow_phone=args.allow_phone)
            if idx is not None:
                print("自動會選用 -> %d: %s" % (idx, nm))
        return

    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    if not os.path.exists(MODEL):
        print("[錯誤] 找不到模型 face_landmarker.task，請先依 README「模型」段取得並放到 obs/engine/。")
        sys.exit(2)

    filters_path = os.path.join(HERE, "filters.json")
    with open(filters_path, "r", encoding="utf-8") as f:
        presets = json.load(f)["presets"]
    active = max(0, min(args.preset, len(presets) - 1))
    need_blend = any(pr.get("lipsync") for pr in presets)   # 只有虛擬人嘴型才需要 blendshapes

    def make_base(path, use_gpu):
        kw = {"model_asset_path": path}
        if use_gpu:
            try:
                kw["delegate"] = mp_python.BaseOptions.Delegate.GPU
            except Exception:
                pass
        return mp_python.BaseOptions(**kw)

    def build_landmarker(use_gpu):
        return vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=make_base(MODEL, use_gpu),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=1,
                output_face_blendshapes=need_blend,
            )
        )
    try:
        landmarker = build_landmarker(args.gpu)
        if args.gpu:
            print("[ok] MediaPipe 使用 GPU delegate")
    except Exception as e:
        if args.gpu:
            print("[note] GPU delegate 不可用（%s），退回 CPU" % type(e).__name__)
        landmarker = build_landmarker(False)

    segmenter = None
    if os.path.exists(MODEL_SEG):
        def build_segmenter(use_gpu):
            return vision.ImageSegmenter.create_from_options(
                vision.ImageSegmenterOptions(
                    base_options=make_base(MODEL_SEG, use_gpu),
                    running_mode=vision.RunningMode.VIDEO,
                    output_confidence_masks=True,
                )
            )
        try:
            segmenter = build_segmenter(args.gpu)
        except Exception:
            segmenter = build_segmenter(False)
        print("[ok] 換背景分割模型已載入")
    else:
        print("[note] 找不到 selfie_segmenter.task，換背景功能停用")

    def open_cam(idx):
        try:
            c = cv2.VideoCapture(idx, CAP_BACKEND)
            c.set(cv2.CAP_PROP_FRAME_WIDTH, args.cap_width)
            c.set(cv2.CAP_PROP_FRAME_HEIGHT, args.cap_height)
            ok, fr = c.read()
            if ok and fr is not None:
                return c, fr
            c.release()
        except Exception as e:      # 權限被拒等:回 None 讓上層給訊息,不要崩潰
            print("[note] 開鏡頭 %s 失敗: %s %s" % (idx, type(e).__name__, e))
        return None, None

    if sys.platform == "darwin":
        # macOS:主動請求相機權限(讓系統跳「允許」對話框,而不是 TCC 靜默拒絕/殺程序)
        try:
            import ctypes, ctypes.util
            avf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("AVFoundation"))
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.objc_msgSend.restype = ctypes.c_long
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            AVCaptureDevice = objc.objc_getClass(b"AVCaptureDevice")
            sel = objc.sel_registerName(b"authorizationStatusForMediaType:")
            # AVMediaTypeVideo 常數字串
            CF = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            CF.CFStringCreateWithCString.restype = ctypes.c_void_p
            CF.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            vide = CF.CFStringCreateWithCString(None, b"vide", 0x08000100)
            status = objc.objc_msgSend(AVCaptureDevice, sel, vide)
            print("[mac] 相機權限狀態: %d (0=未決定 1=受限 2=拒絕 3=允許)" % status)
            if status == 0:
                # 用 requestAccessForMediaType:completionHandler: 正式請求(會跳系統詢問框),
                # 再輪詢狀態最多 60 秒等使用者按「好」;不能只試一次就放棄。
                try:
                    Block = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_bool)
                    _cb = Block(lambda _blk, granted: None)   # 結果靠輪詢讀,回呼不需做事
                    # ObjC block 結構(簡化):isa, flags, reserved, invoke, descriptor
                    class _BlockDesc(ctypes.Structure):
                        _fields_ = [("reserved", ctypes.c_ulong), ("size", ctypes.c_ulong)]
                    class _BlockLit(ctypes.Structure):
                        _fields_ = [("isa", ctypes.c_void_p), ("flags", ctypes.c_int), ("reserved", ctypes.c_int),
                                    ("invoke", ctypes.c_void_p), ("descriptor", ctypes.POINTER(_BlockDesc))]
                    _desc = _BlockDesc(0, ctypes.sizeof(_BlockLit))
                    _NSConcreteGlobalBlock = ctypes.c_void_p.in_dll(objc, "_NSConcreteGlobalBlock")
                    _blk = _BlockLit(ctypes.cast(_NSConcreteGlobalBlock, ctypes.c_void_p), (1 << 28), 0,
                                     ctypes.cast(_cb, ctypes.c_void_p), ctypes.pointer(_desc))
                    req = objc.sel_registerName(b"requestAccessForMediaType:completionHandler:")
                    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                    objc.objc_msgSend(AVCaptureDevice, req, vide, ctypes.byref(_blk))
                    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                except Exception as _e:
                    print("[note] requestAccess 呼叫失敗(%s),改用開鏡頭觸發" % type(_e).__name__)
                    _t = cv2.VideoCapture(0, CAP_BACKEND); time.sleep(1.0); _t.release()
                print("[mac] 等待相機授權(系統會跳出詢問,請按「好」)...")
                for _i in range(120):                     # 最多 60 秒
                    time.sleep(0.5)
                    status = objc.objc_msgSend(AVCaptureDevice, sel, vide)
                    if status in (2, 3):
                        break
                print("[mac] 相機權限狀態(等待後): %d" % status)
            if status == 2:
                print("[錯誤] 相機權限被拒。請到 系統設定→隱私權與安全性→相機 開啟 primelive_filter。")
                if not args.no_window:
                    try:
                        import subprocess
                        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"])
                    except Exception:
                        pass
        except Exception as e:
            print("[note] 相機權限檢查略過: %s" % type(e).__name__)

    if args.fake_camera:
        # 假攝影機:示範圖循環當來源(CI/無鏡頭環境驗整條管線:虛擬cam+濾鏡+UI+OBS遙控)
        _demo = cv2.imread(os.path.join(ASSETS, "demo_female.png"), cv2.IMREAD_COLOR)
        if _demo is None:
            _demo = np.full((720, 1280, 3), 40, np.uint8)
        _demo = cv2.resize(_demo, (args.cap_width, args.cap_height))

        class _FakeCap:
            def __init__(self, *a, **k): self.n = 0
            def set(self, *a): return True
            def read(self):
                self.n += 1
                time.sleep(1.0 / 30)
                fr = _demo.copy()
                cv2.putText(fr, "FAKE CAM %d" % self.n, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                return True, fr
            def release(self): pass
        cv2.VideoCapture = lambda *a, **k: _FakeCap()
        print("[test] 假攝影機模式(示範圖循環)")

    cam_names = ["Fake Camera"] if args.fake_camera else list_camera_names()
    if cam_names:
        print("[鏡頭] " + " | ".join("%d:%s" % (i, n) for i, n in enumerate(cam_names)))

    # 決定主鏡頭：使用者指定索引優先(但若指到手機則改自動)，否則依名稱選 OBSBOT
    target = args.camera
    if target is not None and target >= 0 and cam_names and target < len(cam_names) and _is_phone(cam_names[target]):
        if args.allow_phone:
            print("[note] 使用手機/連線相機：%s" % cam_names[target])
        else:
            print("[警告] 指定的 camera %d 是手機(%s)，改自動選 OBSBOT(要用手機請加 --allow-phone)" % (target, cam_names[target]))
            target = -1
    if target is None or target < 0:
        idx, nm = pick_camera_index(cam_names, args.camera_name, allow_phone=args.allow_phone)
        target = idx if idx is not None else 0
        if nm:
            print("[ok] 自動選用鏡頭 %d：%s" % (target, nm))
    args.camera = target

    # 可切換的實體鏡頭清單(排除虛擬相機;手機除非 --allow-phone)＝視窗「切換鏡頭」用
    cam_choices = [i for i, n in enumerate(cam_names or [])
                   if "virtual" not in n.lower() and (args.allow_phone or not _is_phone(n))]
    if target not in cam_choices and not args.fake_camera:
        cam_choices = ([target] + cam_choices) if cam_names else cam_choices

    cap, frame = open_cam(target)
    if cap is None and args.allow_phone:
        # 手機/連線相機可能要幾秒才連上(手機需按「允許」) → 多等幾次再放棄，避免誤退回 OBSBOT
        print("[note] 等待手機/連線相機連上(請在手機上允許使用相機)...")
        for _ in range(10):
            time.sleep(1.0)
            cap, frame = open_cam(target)
            if cap is not None:
                print("[ok] 手機鏡頭已連上")
                break
    if cap is None:   # 主鏡頭開不了 → 掃描其他可用鏡頭，但永遠跳過手機/連線相機
        scan_n = len(cam_names) if cam_names else 6
        for idx in range(scan_n):
            if idx == target:
                continue
            if cam_names and _is_phone(cam_names[idx]) and not args.allow_phone:
                continue
            cap, frame = open_cam(idx)
            if cap is not None:
                print("[note] 鏡頭 %d 開不了，自動改用鏡頭 %d" % (target, idx))
                args.camera = idx
                break
    if cap is None:
        print("[錯誤] 找不到可用的攝影機。請確認 OBSBOT 已接上、沒被其他程式佔用。")
        sys.exit(3)
    frame = crop_portrait(frame)     # 直播固定直式:輸出尺寸以裁切後為準
    H, W = frame.shape[:2]
    print("[ok] 攝影機 %dx%d，濾鏡 %d 個。左右滑動/←→ 切換，關閉視窗離開。" % (W, H, len(presets)))

    import pyvirtualcam
    OUT_W, OUT_H = W, H                       # 虛擬攝影機固定用第一格的尺寸

    class _NullCam:
        """虛擬攝影機開不了時的替身:視窗/濾鏡/開播鈕照常,只是畫面不送出去(macOS 擴充未啟用時)。"""
        device = "(未啟用)"
        def __init__(self, fps): self._dt = 1.0 / max(1, fps); self._t = time.time()
        def send(self, frame): pass
        def sleep_until_next_frame(self):
            self._t += self._dt
            d = self._t - time.time()
            if d > 0: time.sleep(d)
            else: self._t = time.time()
        def close(self): pass

    cam = None
    try:
        cam = pyvirtualcam.Camera(width=OUT_W, height=OUT_H, fps=args.target_fps, fmt=pyvirtualcam.PixelFormat.RGB)
        print("[ok] 虛擬攝影機已啟動：%s（%dx%d@%d）" % (cam.device, OUT_W, OUT_H, args.target_fps))
    except Exception as e:
        print("[錯誤] 虛擬攝影機無法啟動: %s" % e)
        cam = _NullCam(args.target_fps)
        if sys.platform == "darwin" and not args.no_window:   # 無視窗(CI/測試)時不彈對話框、不開系統設定
            # macOS:OBS 虛擬相機系統擴充未啟用/未允許 → 引導使用者到系統設定,程式不崩潰
            try:
                import subprocess
                subprocess.Popen(["osascript", "-e",
                    'display dialog "第一次使用需要允許「OBS 虛擬相機」擴充功能：\\n\\n'
                    '1) 打開 系統設定 → 一般 → 登入項目與延伸功能\\n'
                    '2) 找到 OBS(或「相機延伸功能」)→ 打開開關 → 輸入密碼\\n'
                    '3) 回來再點一次「開始直播（點我）」\\n\\n'
                    '（這只需要做一次）" buttons {"好"} default button 1 with icon caution with title "primelive"'])
                subprocess.Popen(["open", "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"])
            except Exception:
                pass
    if args.ready_file:                       # 通知「一鍵開播」腳本：虛擬攝影機好了，可以開 OBS
        try:
            with open(args.ready_file, "w", encoding="utf-8") as _rf:
                _rf.write("ready")
        except Exception:
            pass

    threaded = not args.no_threaded
    reader = CameraThread(cap) if threaded else None
    adap = Adaptive(target_fps=args.target_fps, min_scale=args.min_scale, enabled=not args.no_adaptive)
    print("[ok] 防lag：背景抓圖=%s，自動調解析度=%s（目標 %d fps，下限 %.0f%%）"
          % ("開" if threaded else "關", "開" if not args.no_adaptive else "關", args.target_fps, args.min_scale * 100))

    # v8 手機式直式視窗:影像全幅+半透明浮層,濾鏡盤閒置自動收合
    ui = {"active": active, "scroll": 0, "rects": [], "dirty": True, "drag": None,
          "moved": False, "demo": "f", "toggle": False, "live_toggle": False,
          "last_act": time.time(), "tray_vis": 1.0,
          "btn_rect": (0, 0, 0, 0), "handle_rect": (0, 0, 0, 0),
          "chip_rect": (WIN_W - 150, 34, WIN_W - 10, 66),
          "close_rect": (WIN_W - 38, 6, WIN_W - 8, 32), "quit": False,
          "set_rect": (WIN_W - 120, 6, WIN_W - 46, 30), "settings_open": False,
          "cur_cam": args.camera, "do_cam_switch": False, "do_key_change": False}
    strip_tw = TRAY_TW
    demo_imgs = {}
    for g, fn in (("f", "demo_female.png"), ("m", "demo_male.png")):
        im = cv2.imread(os.path.join(ASSETS, fn), cv2.IMREAD_COLOR)
        if im is not None:
            demo_imgs[g] = im
    if demo_imgs:
        dh, dw = demo_imgs["f" if "f" in demo_imgs else list(demo_imgs)[0]].shape[:2]
        strip_th = max(40, int(strip_tw * dh / float(dw)))
    else:
        strip_th = min(100, max(40, int(strip_tw * H / float(W))))   # 後備:裁切後(直式)比例,設上限
        ui["demo"] = "live"
    thumbs_map = {g: [None] * len(presets) for g in (demo_imgs or {"live": None})}
    worker = ThumbWorker(presets, ASSETS)
    obs_ctl = ObsControl()
    WIN = "primelive"    # OpenCV 視窗標題不支援中文(會亂碼),用純英文
    if not args.no_window:
        def _on_mouse(event, x, y, flags, param):
            x = int(x / UI_SCALE); y = int(y / UI_SCALE)   # 顯示座標→基準座標
            ui["last_act"] = time.time()          # 任何滑鼠動作=喚醒濾鏡盤
            if event == cv2.EVENT_MOUSEWHEEL:
                step = (strip_tw + 6) * 2
                ui["scroll"] += -step if flags > 0 else step
                ui["dirty"] = True
            elif event == cv2.EVENT_LBUTTONDOWN:
                ui["drag"] = (x, ui["scroll"]); ui["moved"] = False
            elif event == cv2.EVENT_MOUSEMOVE and ui["drag"] is not None:
                dx = x - ui["drag"][0]
                if abs(dx) > 4:
                    ui["moved"] = True
                    ui["scroll"] = ui["drag"][1] - dx
                    ui["dirty"] = True
            elif event == cv2.EVENT_LBUTTONUP:
                if ui["drag"] is not None and not ui["moved"]:
                    # 設定選單開啟時:優先處理選單點擊(其餘 UI 讓位)
                    if ui.get("settings_open"):
                        px, py = ui.get("_set_pos", (30, 180))
                        for k, (rx0, ry0, rx1, ry1) in ui.get("_set_rects", {}).items():
                            if px + rx0 <= x <= px + rx1 and py + ry0 <= y <= py + ry1:
                                if k == "cam":   ui["do_cam_switch"] = True
                                elif k == "key": ui["do_key_change"] = True
                                ui["settings_open"] = False; ui["dirty"] = True
                                break
                        else:
                            ui["settings_open"] = False; ui["dirty"] = True   # 點面板外=關閉
                        ui["drag"] = None
                        return
                    bx0, by0, bx1, by1 = ui["btn_rect"]
                    cx0, cy0, cx1, cy1 = ui["chip_rect"]
                    qx0, qy0, qx1, qy1 = ui["close_rect"]
                    sx0, sy0, sx1, sy1 = ui["set_rect"]
                    if qx0 <= x <= qx1 and qy0 <= y <= qy1:
                        ui["quit"] = True                # 右上 ✕:結束程式
                    elif sx0 <= x <= sx1 and sy0 <= y <= sy1:
                        ui["settings_open"] = True; ui["dirty"] = True   # 設定鈕
                    elif bx0 <= x <= bx1 and by0 <= y <= by1:
                        ui["live_toggle"] = True     # 開始/停止直播
                    elif cx0 <= x <= cx1 and cy0 <= y <= cy1:
                        ui["toggle"] = True          # 示範模特切換
                    else:
                        for (x0, y0, x1, y1, idx) in ui["rects"]:
                            if x0 <= x < x1 and y0 <= y < y1:
                                ui["active"] = idx; ui["dirty"] = True
                ui["drag"] = None
        cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WIN, _on_mouse)
        print("[ui] 螢幕高 %d → 顯示倍率 %.2f,視窗 %dx%d" % (_screen_h(), UI_SCALE, DISP_W, DISP_H))
        # 開場就用示範圖生成縮圖(不等攝影機)
        if demo_imgs:
            worker.start(demo_imgs[ui["demo"]], strip_tw, strip_th, thumbs_map[ui["demo"]])

    n = 0
    t0 = time.time()
    seg_state = None    # (前景遮罩 m3, 已預乘的背景 bg*(1-m3))
    seg_size = None     # seg_state 對應的處理解析度，變了要重算
    last_seq = -1
    last_full = None    # 上一格輸出（沒有新畫面時直接重送，省 CPU）
    fps_ema = float(args.target_fps)
    try:
        while True:
            # 濾鏡切換即時反映（點按鈕/按鍵）
            if ui["active"] != active:
                active = ui["active"]
                seg_state = None
            p = presets[active]

            # 取一格：背景執行緒永遠給最新、丟舊格；沒新的就重送上一格、不重算
            if threaded:
                ok, frame, seq = reader.read()
                if not ok:
                    time.sleep(0.003)
                    continue
                is_new = (seq != last_seq)
                last_seq = seq
            else:
                ok, frame = cap.read()
                if not ok:
                    break
                is_new = True

            res = None
            if is_new:
                frame = crop_portrait(frame)     # 直式鏈路:進管線先裁
                t_proc = time.time()
                # 自動調解析度：在縮小後的畫面跑整條管線，最後再放大送出
                pw, ph = adap.proc_size(OUT_W, OUT_H)
                if seg_size != (pw, ph):
                    seg_state = None
                    seg_size = (pw, ph)
                proc = frame if (pw == OUT_W and ph == OUT_H) else cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(proc, cv2.COLOR_BGR2RGB)
                ts = int((time.time() - t0) * 1000) + n  # 單調遞增時間戳
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                out = rgb.copy()

                # 臉部關鍵點（貼紙 / 美顏 需要）
                lms = None
                if p.get("sticker") or p.get("beauty") or p.get("warp"):
                    res = landmarker.detect_for_video(mp_img, ts)
                    if res.face_landmarks:
                        lms = res.face_landmarks[0]

                # 1) 換背景（人像分割 + 合成）— 每 seg_every 格才重算遮罩，其餘重用
                if p.get("background") and segmenter is not None:
                    if seg_state is None or (n % args.seg_every == 0):
                        small = np.ascontiguousarray(cv2.resize(rgb, (384, 216)))
                        seg = segmenter.segment_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=small), ts)
                        bg = load_bg(os.path.join(ASSETS, p["background"]), pw, ph)
                        if seg.confidence_masks and bg is not None:
                            m = np.asarray(seg.confidence_masks[0].numpy_view(), dtype=np.float32)
                            m = cv2.GaussianBlur(cv2.resize(m, (pw, ph)), (0, 0), 3.0)[..., None]
                            seg_state = (m, bg.astype(np.float32) * (1.0 - m))
                    if seg_state is not None:
                        m3, bg_pre = seg_state
                        out = (out.astype(np.float32) * m3 + bg_pre).astype(np.uint8)

                # 2) 美顏（磨皮 + 瘦臉 + 化妝：魚尾紋/亮眼/唇彩/腮紅/修容）
                if p.get("beauty") and lms is not None:
                    out = apply_beauty(out, lms, p["beauty"])

                # 2.5) 搞笑變形（大眼 / 大嘴）
                if p.get("warp") and lms is not None:
                    w = p["warp"]
                    out = apply_warp(out, lms, float(w.get("eye", 0.0)), float(w.get("mouth", 0.0)))

                # 3) LUT 調色
                if p.get("lut"):
                    out = apply_lut(out, load_cube(os.path.join(ASSETS, p["lut"])))

                # 4) 貼紙 / 換頭 / 面具（關鍵點錨定）
                if p.get("sticker") and lms is not None:
                    if p.get("anchor") == "head":
                        cx, cy, tw, ang = head_placement(lms, pw, ph, p.get("scale", 2.2), p.get("y_off", -0.15))
                    else:
                        cx, cy, tw, ang = crown_placement(lms, pw, ph)
                    out = overlay(out, load_sticker(os.path.join(ASSETS, p["sticker"])), cx, cy, tw, ang)
                    if p.get("lipsync"):
                        out = draw_mouth(out, cx, cy, tw, ang, jaw_open(res), p["lipsync"])

                # 放大回輸出解析度
                out_full = out if (pw == OUT_W and ph == OUT_H) else cv2.resize(out, (OUT_W, OUT_H), interpolation=cv2.INTER_LINEAR)
                last_full = out_full
                dt = time.time() - t_proc           # 純處理耗時（不含 sleep）→ 回饋給自動調解析度
                adap.update(dt)
                fps_ema = fps_ema * 0.9 + (1.0 / max(1e-3, dt)) * 0.1
                n += 1

            if last_full is not None:
                cam.send(last_full)
            cam.sleep_until_next_frame()

            if not args.no_window:
                # 示範模特切換;該組還沒生成就背景生成
                if ui["toggle"]:
                    ui["toggle"] = False
                    order_g = [g for g in ("f", "m") if g in demo_imgs]
                    if len(order_g) > 1:
                        ui["demo"] = order_g[(order_g.index(ui["demo"]) + 1) % len(order_g)]
                        g = ui["demo"]
                        if thumbs_map[g][0] is None and not worker.busy:
                            worker.start(demo_imgs[g], strip_tw, strip_th, thumbs_map[g])
                        ui["dirty"] = True
                # 後備:沒示範圖時用(已裁直式的)攝影機畫面生縮圖
                if (not demo_imgs) and is_new and n == 8 and not worker.busy \
                        and thumbs_map.get("live") and thumbs_map["live"][0] is None:
                    worker.start(frame, strip_tw, strip_th, thumbs_map["live"])
                # 開始/停止直播(遙控背景 OBS,不卡輸出)
                # 切換鏡頭(熱換,不重開;開不了就跳回上一個並提示)
                if ui.get("do_cam_switch"):
                    ui["do_cam_switch"] = False
                    if reader is not None and cam_choices and len(cam_choices) > 1:
                        cur = ui.get("cur_cam", args.camera)
                        pos = cam_choices.index(cur) if cur in cam_choices else 0
                        nxt = cam_choices[(pos + 1) % len(cam_choices)]
                        newcap, _f = open_cam(nxt)
                        if newcap is not None:
                            reader.swap(newcap)
                            ui["cur_cam"] = nxt; args.camera = nxt
                            nm = cam_names[nxt] if nxt < len(cam_names) else str(nxt)
                            ui["toast"] = ("已切換鏡頭：" + nm, time.time() + 4)
                            try:    # 記住選擇(下次開機沿用)
                                base = (os.environ.get("APPDATA", "") if sys.platform == "win32"
                                        else os.path.expanduser("~/Library/Application Support"))
                                dp = os.path.join(base, "PrimeStage", "devices.json")
                                dd = json.load(open(dp, encoding="utf-8")) if os.path.exists(dp) else {}
                                dd["cameraName"] = nm
                                os.makedirs(os.path.dirname(dp), exist_ok=True)
                                json.dump(dd, open(dp, "w", encoding="utf-8"), ensure_ascii=False)
                            except Exception:
                                pass
                        else:
                            nm = cam_names[nxt] if nxt < len(cam_names) else str(nxt)
                            ui["toast"] = ("鏡頭「%s」無法開啟(可能被其他程式佔用)" % nm, time.time() + 6)
                    else:
                        ui["toast"] = ("只偵測到一個鏡頭,無法切換", time.time() + 4)
                    ui["dirty"] = True
                # 換直播金鑰(跳輸入框→寫 service.json→即時推給 OBS)
                if ui.get("do_key_change"):
                    ui["do_key_change"] = False
                    newkey = _prompt_key()
                    if newkey:
                        if _write_stream_key(newkey):
                            obs_ctl.set_stream_key_async(newkey)
                            ui["toast"] = ("金鑰已更新", time.time() + 4)
                        else:
                            ui["toast"] = ("金鑰寫入失敗", time.time() + 5)
                    ui["dirty"] = True
                if ui.get("live_toggle"):
                    ui["live_toggle"] = False
                    ui["toggle_at"] = time.time()
                    ui["toggle_was"] = obs_ctl.streaming
                    if not obs_ctl.connected:
                        obs_ctl.ensure_obs_async()      # 沒連上就先把 OBS 帶起來/等它開埠
                        ui["toast"] = ("準備 OBS 中…請稍候再按一次", time.time() + 8)
                    else:
                        obs_ctl.toggle_stream_async()
                    ui["dirty"] = True
                # 按下後 4 秒內若狀態沒變且未連線 → 顯示提示(按鈕一定有反應)
                if ui.get("toggle_at") and not obs_ctl.busy and time.time() - ui["toggle_at"] > 4:
                    if obs_ctl.streaming == ui.get("toggle_was") and not obs_ctl.connected:
                        _dg = getattr(obs_ctl, "diag", "") or "連線中"
                        ui["toast"] = ("連不到 OBS(%s),請截圖給小編" % _dg, time.time() + 8)
                    ui["toggle_at"] = None
                    ui["dirty"] = True
                if n == 30:
                    obs_ctl.ensure_obs_async()      # 開場就確保 OBS 起來+websocket 通
                elif n % 240 == 0:                  # 之後定期同步狀態(~8秒)
                    obs_ctl.poll_async()
                # 浮層快取(髒/縮圖進度/直播狀態變了才重建)
                lstate = (obs_ctl.streaming, obs_ctl.connected, obs_ctl.busy or getattr(obs_ctl, "_ensuring", False))
                ver = worker.version
                if ui["dirty"] or ver != ui.get("_ver") or lstate != ui.get("_ls"):
                    live = {"streaming": lstate[0], "connected": lstate[1], "busy": lstate[2]}
                    demo_label = ""
                    if len(demo_imgs) > 1:
                        demo_label = "示範:女→男" if ui["demo"] == "f" else "示範:男→女"
                    cur_thumbs = thumbs_map.get(ui["demo"]) or worker.thumbs
                    tray, trects, max_sc, tray_h = build_tray(presets, cur_thumbs,
                                                              ui["active"], ui["scroll"],
                                                              strip_tw, strip_th)
                    ui["scroll"] = max(0, min(ui["scroll"], max_sc))
                    ui["_tray"] = tray; ui["_trects"] = trects; ui["_tray_h"] = tray_h
                    ui["_top"] = build_topbar(presets[ui["active"]], demo_label, live)
                    ui["_btn"] = build_livebtn(live)
                    ui["_handle"] = build_handle()
                    ui["_ver"] = ver; ui["_ls"] = lstate
                    ui["dirty"] = False
                # 閒置 3 秒自動收合;任何操作喚醒(緩動動畫)
                target = 0.0 if (time.time() - ui["last_act"] > 3.0) else 1.0
                ui["tray_vis"] += (target - ui["tray_vis"]) * 0.22
                tv = max(0.0, min(1.0, ui["tray_vis"]))
                # 每格合成:直式畫面全幅 + 半透明浮層
                if last_full is not None:
                    view = cv2.resize(cv2.cvtColor(last_full, cv2.COLOR_RGB2BGR), (WIN_W, WIN_H))
                else:
                    view = np.full((WIN_H, WIN_W, 3), 16, np.uint8)
                if ui.get("_top") is not None:
                    _alpha_paste(view, ui["_top"], 0, 0)
                    tray_h = ui.get("_tray_h", 100)
                    tray_y = WIN_H - int(tray_h * tv)
                    if tv > 0.02:
                        _alpha_paste(view, ui["_tray"], 0, tray_y)
                        ui["rects"] = [(x0, y0 + tray_y, x1, y1 + tray_y, i)
                                       for (x0, y0, x1, y1, i) in ui.get("_trects", [])]
                    else:
                        ui["rects"] = []
                    if tv < 0.5:
                        hb = ui["_handle"]
                        hx = (WIN_W - hb.shape[1]) // 2; hy = WIN_H - hb.shape[0] - 6
                        _alpha_paste(view, hb, hx, hy)
                        ui["handle_rect"] = (hx, hy, hx + hb.shape[1], hy + hb.shape[0])
                    else:
                        ui["handle_rect"] = (0, 0, 0, 0)
                    btn = ui["_btn"]
                    bx = (WIN_W - btn.shape[1]) // 2
                    by = (tray_y - btn.shape[0] - 10) if tv > 0.02 else (WIN_H - btn.shape[0] - 34)
                    _alpha_paste(view, btn, bx, by)
                    ui["btn_rect"] = (bx, by, bx + btn.shape[1], by + btn.shape[0])
                    # 提示 toast(按鈕上方,半透明)
                    tz = ui.get("toast")
                    if tz and time.time() < tz[1]:
                        _tim = PILImage.new("RGBA", (WIN_W - 24, 50), (0, 0, 0, 0))
                        _td = PILDraw.Draw(_tim)
                        _td.rounded_rectangle([0, 0, WIN_W - 25, 49], radius=12, fill=(30, 14, 14, 240))
                        _td.text(((WIN_W - 24) / 2, 25), tz[0], font=_uifont("zhb", 16), fill=(255, 230, 220, 255), anchor="mm")
                        _alpha_paste(view, _rgba(_tim), 12, by - 62)
                    elif tz:
                        ui["toast"] = None
                # 設定面板(切換鏡頭/換金鑰)蓋在最上層
                if ui.get("settings_open"):
                    cur_cam_name = cam_names[ui.get("cur_cam", 0)] if (cam_names and ui.get("cur_cam", 0) < len(cam_names)) else "—"
                    panel, srects, spos = build_settings_panel(cur_cam_name)
                    ui["_set_rects"] = srects; ui["_set_pos"] = spos
                    _alpha_paste(view, panel, spos[0], spos[1])
                if UI_SCALE > 1.01:
                    view = cv2.resize(view, (DISP_W, DISP_H), interpolation=cv2.INTER_LINEAR)
                cv2.imshow(WIN, view)
                # 鍵盤:← →(Windows 2424832/2555904;macOS 63234/63235) 換濾鏡;Esc/Q 關閉;關閉視窗(X)= 離開
                k = cv2.waitKeyEx(1)
                kc = (k & 0xFF) if k > 0 else -1
                if kc in (27, ord("q"), ord("Q")) or ui.get("quit"):
                    break
                if k in (2424832, 2555904, 63234, 63235):
                    ui["last_act"] = time.time()
                    step = -1 if k in (2424832, 63234) else 1
                    ui["active"] = (ui["active"] + step) % len(presets)
                    tx = 10 + ui["active"] * (strip_tw + 6)
                    if tx - ui["scroll"] < 10:
                        ui["scroll"] = tx - 10
                    elif tx - ui["scroll"] + strip_tw > WIN_W - 10:
                        ui["scroll"] = tx + strip_tw - WIN_W + 10
                    ui["dirty"] = True
                try:
                    if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except Exception:
                    pass

            if args.frames and n >= args.frames:
                faces = 1 if (res and res.face_landmarks) else 0
                print("[煙霧測試] 跑了 %d 格，最後一格偵測到臉=%d，fps~%.1f，末端 scale=%.2f"
                      % (n, faces, n / max(1e-6, time.time() - t0), adap.scale))
                break
    finally:
        # 收尾:直播中先停止,再請 OBS 優雅關閉(不留背景程序)
        try:
            if 'obs_ctl' in locals() and obs_ctl.connected:
                if obs_ctl.streaming:
                    try: obs_ctl._rpc("StopStream")
                    except Exception: pass
                try:
                    import subprocess as _sp
                    if sys.platform == "darwin":
                        _sp.Popen(["osascript", "-e", 'quit app "OBS"'])
                    elif sys.platform == "win32":
                        _sp.Popen(["taskkill", "/IM", "obs64.exe"], creationflags=0x08000000)
                except Exception:
                    pass
        except Exception:
            pass
        cam.close()
        if threaded and reader is not None:
            reader.stop()
        elif cap is not None:
            cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
