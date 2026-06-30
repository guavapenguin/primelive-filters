"""靜態圖驗證化妝管線：拿 assets/妝前.png 跑數種妝感，與 妝後.png 並排輸出 _mk_compare.png。
不需攝影機。用法： .venv\\Scripts\\python.exe _test_makeup.py
"""
import os
import sys
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import primelive_engine as pe  # noqa: E402

import mediapipe as mp  # noqa: E402
from mediapipe.tasks import python as mpp  # noqa: E402
from mediapipe.tasks.python import vision  # noqa: E402

ASSETS = os.path.join(os.path.dirname(HERE), "assets")


def imread_u(path):
    """Windows 下 cv2.imread 無法讀中文檔名，改用 imdecode。"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def detect(img_rgb):
    lm = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=os.path.join(HERE, "face_landmarker.task")),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
        )
    )
    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img_rgb)))
    return res.face_landmarks[0] if res.face_landmarks else None


LOOKS = {
    "1_natural": {"smooth": 0.45, "slim": 0.06, "wrinkle": 0.55, "brighten_eyes": 0.18,
                  "lipstick": [172, 96, 102], "lip_strength": 0.35,
                  "blush": [236, 150, 156], "blush_strength": 0.13},
    "2_daily":   {"smooth": 0.55, "slim": 0.12, "wrinkle": 0.75, "brighten_eyes": 0.28,
                  "lipstick": [160, 80, 92], "lip_strength": 0.50,
                  "blush": [232, 138, 150], "blush_strength": 0.20, "contour": 0.18},
    "3_glam":    {"smooth": 0.65, "slim": 0.18, "wrinkle": 0.90, "brighten_eyes": 0.35,
                  "lipstick": [150, 58, 78], "lip_strength": 0.62,
                  "blush": [230, 118, 140], "blush_strength": 0.26, "contour": 0.28},
}


def label(img_bgr, text):
    cv2.rectangle(img_bgr, (0, 0), (img_bgr.shape[1], 34), (30, 30, 30), -1)
    cv2.putText(img_bgr, text, (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return img_bgr


def main():
    before = imread_u(os.path.join(ASSETS, "妝前.png"))
    rgb = cv2.cvtColor(before, cv2.COLOR_BGR2RGB)
    lms = detect(rgb)
    if lms is None:
        print("[錯誤] 妝前圖偵測不到臉")
        sys.exit(1)
    print("[ok] 偵測到臉，關鍵點 %d 個，影像 %dx%d" % (len(lms), rgb.shape[1], rgb.shape[0]))

    panels = [label(before.copy(), "before")]
    for name, p in LOOKS.items():
        out = pe.apply_beauty(rgb.copy(), lms, p)
        bgr = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
        cv2.imwrite(os.path.join(HERE, "_mk_%s.png" % name), bgr)
        panels.append(label(bgr.copy(), name))

    after_path = os.path.join(ASSETS, "妝後.png")
    if os.path.exists(after_path):
        panels.append(label(imread_u(after_path), "REAL after"))

    h = 760
    row = [cv2.resize(p, (int(p.shape[1] * h / p.shape[0]), h)) for p in panels]
    out_path = os.path.join(HERE, "_mk_compare.png")
    cv2.imwrite(out_path, np.hstack(row))
    print("[ok] 輸出對比圖：%s" % out_path)


if __name__ == "__main__":
    main()
