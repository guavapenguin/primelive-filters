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

# Windows 主控台預設 cp950，改成 utf-8 才能印中文與特殊符號
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

def load_cube(path):
    """解析 .cube，並預先展開成 256^3 的 uint8 直查表(索引 [R,G,B])，每格套用只剩一次查表。"""
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
    li = np.clip(np.round(np.arange(256) / 255.0 * (size - 1)), 0, size - 1).astype(np.intp)
    big = (table[li.reshape(1, 1, 256), li.reshape(1, 256, 1), li.reshape(256, 1, 1)] * 255.0).astype(np.uint8)
    _lut_cache[path] = big   # shape (256,256,256,3)，索引 [R,G,B]
    return big

def apply_lut(rgb, big):
    return big[rgb[..., 0], rgb[..., 1], rgb[..., 2]]

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
    pad = int(0.2 * max(wf, hf))
    X0, Y0 = max(0, x - pad), max(0, y - pad)
    X1, Y1 = min(W, x + wf + pad), min(H, y + hf + pad)
    if X1 <= X0 or Y1 <= Y0:
        return rgb
    ys, xs = np.mgrid[Y0:Y1, X0:X1].astype(np.float32)
    span = max(1.0, (ymax - ymin) * 0.7)
    vw = np.clip((ys - (ymin + (ymax - ymin) * 0.3)) / span, 0.0, 1.0)  # 下半臉權重高
    map_x = (xs + (xs - cx) * strength * vw - X0).astype(np.float32)
    map_y = (ys - Y0).astype(np.float32)
    warped = cv2.remap(rgb[Y0:Y1, X0:X1], map_x, map_y,
                       interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    out = rgb.copy()
    out[Y0:Y1, X0:X1] = warped
    return out

def apply_beauty(rgb, lms, smooth=0.5, slim=0.0):
    H, W = rgb.shape[:2]
    pts = _face_pts(lms, W, H)
    out = rgb
    if slim > 0:
        out = slim_face(out, pts, slim)
    if smooth > 0:
        x, y, wf, hf = cv2.boundingRect(pts.astype(np.int32))
        pad = int(0.15 * max(wf, hf))
        X0, Y0 = max(0, x - pad), max(0, y - pad)
        X1, Y1 = min(W, x + wf + pad), min(H, y + hf + pad)
        if X1 > X0 and Y1 > Y0:
            roi = out[Y0:Y1, X0:X1]
            sm = cv2.bilateralFilter(roi, 9, 45, 45)
            mask = np.zeros((Y1 - Y0, X1 - X0), np.float32)
            hull = cv2.convexHull((pts - [X0, Y0]).astype(np.int32))
            cv2.fillConvexPoly(mask, hull, 1.0)
            mask = (cv2.GaussianBlur(mask, (0, 0), 8.0) * smooth)[..., None]
            out = out.copy()
            out[Y0:Y1, X0:X1] = (roi.astype(np.float32) * (1 - mask) + sm.astype(np.float32) * mask).astype(np.uint8)
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

def build_panel(presets, active, W):
    """畫一排可點擊的中文大按鈕面板（只在 active 改變時重畫，快取）。回傳 (面板BGR, 命中矩形, 高)。"""
    if active in _panel_cache:
        return _panel_cache[active]
    cols = 5
    rows = (len(presets) + cols - 1) // cols
    bw = W // cols
    bh = 62
    pil = PILImage.new("RGB", (W, rows * bh), (22, 22, 26))
    d = PILDraw.Draw(pil)
    f, fk = _font(20), _font(14)
    rects = []
    for i, pr in enumerate(presets):
        r, c = divmod(i, cols)
        x0, y0 = c * bw, r * bh
        on = (i == active)
        d.rectangle([x0 + 3, y0 + 3, x0 + bw - 3, y0 + bh - 3], fill=(60, 150, 95) if on else (48, 48, 56))
        d.text((x0 + 12, y0 + 6), "[" + str(pr["key"]) + "]", font=fk, fill=(225, 240, 225) if on else (150, 150, 160))
        d.text((x0 + 12, y0 + 26), pr["name"], font=f, fill=(255, 255, 255) if on else (205, 205, 210))
        rects.append((x0, y0, x0 + bw, y0 + bh, i))
    panel = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    _panel_cache[active] = (panel, rects, rows * bh)
    return _panel_cache[active]


# ---------- 主程式 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=3)  # 本機 cam 3 = OBSBOT(可用 --camera 覆蓋)
    ap.add_argument("--frames", type=int, default=0, help="只跑 N 格就結束(煙霧測試)")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--preset", type=int, default=0, help="起始濾鏡索引(0-based)")
    ap.add_argument("--seg-every", type=int, default=3, help="每幾格重算一次換背景遮罩")
    ap.add_argument("--cap-width", type=int, default=1280, help="擷取寬(降到 960 可衝 fps)")
    ap.add_argument("--cap-height", type=int, default=720)
    ap.add_argument("--fast", action="store_true", help="快速模式：540p 換更高 fps")
    args = ap.parse_args()
    if args.fast:
        args.cap_width, args.cap_height = 960, 540

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

    landmarker = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MODEL),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,   # 給虛擬人嘴型同步用(jawOpen)
        )
    )

    segmenter = None
    if os.path.exists(MODEL_SEG):
        segmenter = vision.ImageSegmenter.create_from_options(
            vision.ImageSegmenterOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL_SEG),
                running_mode=vision.RunningMode.VIDEO,
                output_confidence_masks=True,
            )
        )
        print("[ok] 換背景分割模型已載入")
    else:
        print("[note] 找不到 selfie_segmenter.task，換背景功能停用")

    def open_cam(idx):
        c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        c.set(cv2.CAP_PROP_FRAME_WIDTH, args.cap_width)
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, args.cap_height)
        ok, fr = c.read()
        if ok and fr is not None:
            return c, fr
        c.release()
        return None, None

    cap, frame = open_cam(args.camera)
    if cap is None:   # 指定的攝影機開不了 → 自動掃描 0~5 找可用的（給別台電腦用）
        for idx in range(6):
            if idx == args.camera:
                continue
            cap, frame = open_cam(idx)
            if cap is not None:
                print("[note] camera %d 開不了，自動改用 camera %d" % (args.camera, idx))
                args.camera = idx
                break
    if cap is None:
        print("[錯誤] 找不到可用的攝影機。請確認攝影機已接上、沒被其他程式佔用。")
        sys.exit(3)
    H, W = frame.shape[:2]
    print("[ok] 攝影機 %dx%d，濾鏡 %d 個。數字鍵切換，q 離開。" % (W, H, len(presets)))

    import pyvirtualcam
    cam = pyvirtualcam.Camera(width=W, height=H, fps=30, fmt=pyvirtualcam.PixelFormat.RGB)
    print("[ok] 虛擬攝影機已啟動：%s" % cam.device)

    ui = {"active": active, "H": H, "rects": []}
    if not args.no_window:
        def _on_mouse(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                yy = y - ui["H"]
                for (x0, y0, x1, y1, idx) in ui["rects"]:
                    if x0 <= x < x1 and y0 <= yy < y1:
                        ui["active"] = idx
        cv2.namedWindow("primelive engine")
        cv2.setMouseCallback("primelive engine", _on_mouse)

    n = 0
    t0 = time.time()
    seg_state = None   # (前景遮罩 m3, 已預乘的背景 bg*(1-m3))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ts = int((time.time() - t0) * 1000) + n  # 單調遞增時間戳
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            if ui["active"] != active:
                active = ui["active"]
                seg_state = None
            p = presets[active]
            out = rgb.copy()

            # 臉部關鍵點（貼紙 / 美顏 需要）
            res = None
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
                    bg = load_bg(os.path.join(ASSETS, p["background"]), W, H)
                    if seg.confidence_masks and bg is not None:
                        m = np.asarray(seg.confidence_masks[0].numpy_view(), dtype=np.float32)
                        m = cv2.GaussianBlur(cv2.resize(m, (W, H)), (0, 0), 3.0)[..., None]
                        seg_state = (m, bg.astype(np.float32) * (1.0 - m))
                if seg_state is not None:
                    m3, bg_pre = seg_state
                    out = (out.astype(np.float32) * m3 + bg_pre).astype(np.uint8)

            # 2) 美顏（磨皮 + 瘦臉）
            if p.get("beauty") and lms is not None:
                b = p["beauty"]
                out = apply_beauty(out, lms, float(b.get("smooth", 0.5)), float(b.get("slim", 0.0)))

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
                    cx, cy, tw, ang = head_placement(lms, W, H, p.get("scale", 2.2), p.get("y_off", -0.15))
                else:
                    cx, cy, tw, ang = crown_placement(lms, W, H)
                out = overlay(out, load_sticker(os.path.join(ASSETS, p["sticker"])), cx, cy, tw, ang)
                if p.get("lipsync"):
                    out = draw_mouth(out, cx, cy, tw, ang, jaw_open(res), p["lipsync"])

            cam.send(out)
            cam.sleep_until_next_frame()

            if not args.no_window:
                disp = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
                panel, rects, _ = build_panel(presets, active, W)
                ui["rects"] = rects
                cv2.imshow("primelive engine", np.vstack([disp, panel]))
                k = cv2.waitKey(1) & 0xFF
                if k == ord("q"):
                    break
                elif k in (ord("="), ord("+")) and "scale" in presets[active]:
                    presets[active]["scale"] = round(presets[active]["scale"] + 0.1, 2)
                    print("  scale =", presets[active]["scale"])
                elif k == ord("-") and "scale" in presets[active]:
                    presets[active]["scale"] = round(presets[active]["scale"] - 0.1, 2)
                    print("  scale =", presets[active]["scale"])
                elif k == ord("]") and presets[active].get("anchor") == "head":
                    presets[active]["y_off"] = round(presets[active].get("y_off", -0.15) + 0.02, 3)
                    print("  y_off =", presets[active]["y_off"])
                elif k == ord("[") and presets[active].get("anchor") == "head":
                    presets[active]["y_off"] = round(presets[active].get("y_off", -0.15) - 0.02, 3)
                    print("  y_off =", presets[active]["y_off"])
                elif k == ord("o"):
                    with open(filters_path, "w", encoding="utf-8") as f:
                        json.dump({"presets": presets}, f, ensure_ascii=False, indent=2)
                    print("  已存回 filters.json")
                elif k == ord("n"):   # 切換到下一個可用攝影機
                    cap.release()
                    nxt, newcap = args.camera, None
                    for _ in range(6):
                        nxt = (nxt + 1) % 6
                        newcap, _ = open_cam(nxt)
                        if newcap is not None:
                            break
                    if newcap is not None:
                        cap, args.camera = newcap, nxt
                        print("  -> 切換攝影機 camera", nxt)
                    else:
                        cap, _ = open_cam(args.camera)
                        print("  找不到其他攝影機")
                else:
                    for i, pr in enumerate(presets):
                        if k == ord(pr["key"]):
                            ui["active"] = i

            n += 1
            if args.frames and n >= args.frames:
                faces = 1 if (res and res.face_landmarks) else 0
                print("[煙霧測試] 跑了 %d 格，最後一格偵測到臉=%d，fps~%.1f"
                      % (n, faces, n / max(1e-6, time.time() - t0)))
                break
    finally:
        cam.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
