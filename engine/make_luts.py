# -*- coding: utf-8 -*-
"""
primelive 色彩濾鏡 LUT 生成器(我們自己的參數化建構,非散布他人素材)。
looks 的參數是照「量測 OBSBOT LUT 對中灰/膚色的位移+對比」反推的等價調色配方。
產出 .cube(LUT_3D_SIZE 33)到 assets/luts/,引擎既有 load_cube/apply_lut 直接吃。
"""
import numpy as np, os

SIZE = 33
OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "luts")

def grade(rgb, p):
    """rgb: (...,3) float 0..1。參數化調色:白平衡增益→提亮→陰影抬升(褪色)→對比→分離色調→飽和。"""
    x = rgb.copy()
    g = np.array(p.get("gain", [1, 1, 1]), np.float32)      # 白平衡(冷暖/色偏)
    x = x * g
    x = x + p.get("bright", 0.0)                            # 整體提亮
    lift = p.get("lift", 0.0)                               # 陰影抬升(黑不死=膠片褪色)
    x = x * (1 - lift) + lift
    c = p.get("contrast", 1.0)                              # 對比(繞中點)
    x = (x - 0.5) * c + 0.5
    st = p.get("split")                                     # 分離色調:陰影/高光染色
    if st:
        luma = (x * np.array([0.299, 0.587, 0.114])).sum(-1, keepdims=True)
        sh = np.array(st.get("shadow", [0, 0, 0]), np.float32)
        hi = np.array(st.get("high", [0, 0, 0]), np.float32)
        x = x + sh * (1 - luma) + hi * luma
    s = p.get("sat", 1.0)                                   # 飽和度
    if s != 1.0:
        luma = (x * np.array([0.299, 0.587, 0.114])).sum(-1, keepdims=True)
        x = luma + (x - luma) * s
    if p.get("mono"):                                       # 黑白
        luma = (x * np.array([0.299, 0.587, 0.114])).sum(-1, keepdims=True)
        x = np.repeat(luma, 3, -1) + np.array(p.get("mono_tint", [0, 0, 0]), np.float32)
    return np.clip(x, 0, 1)

# 14 款熱門看(名稱=我們自己的命名;配方對齊量測數據)
LOOKS = [
    ("primelive_jing_baixi",  {"gain":[1.02,1.05,1.10],"bright":0.10,"contrast":0.90,"sat":1.03}),   # 淨白皙
    ("primelive_bainen",      {"gain":[1.06,1.06,1.09],"bright":0.09,"contrast":0.92,"sat":1.05}),   # 白嫩
    ("primelive_ziran_liang", {"gain":[1.05,1.04,1.05],"bright":0.08,"contrast":0.98,"sat":1.06}),   # 自然亮
    ("primelive_shuiguang",   {"gain":[1.02,1.03,1.04],"bright":0.03,"contrast":1.05,"sat":1.10,"split":{"high":[0.02,0.02,0.03]}}),  # 水光
    ("primelive_nuandiao",    {"gain":[1.08,1.03,0.98],"bright":0.06,"contrast":0.82,"sat":1.02}),   # 暖調
    ("primelive_qingtou",     {"gain":[1.00,1.05,1.09],"bright":0.06,"contrast":0.92,"sat":1.04}),   # 清透
    ("primelive_weifeng",     {"gain":[1.02,1.05,1.08],"bright":0.05,"contrast":0.85,"sat":0.98}),   # 微風
    ("primelive_tianxin",     {"gain":[1.08,1.02,1.03],"bright":0.05,"contrast":0.86,"sat":1.10,"split":{"shadow":[0.02,0.0,0.02]}}),  # 甜心
    ("primelive_meihuo",      {"gain":[1.03,1.00,1.02],"bright":0.02,"contrast":1.12,"sat":1.16}),   # 魅惑
    ("primelive_jiudiao",     {"gain":[1.04,1.00,0.94],"bright":0.02,"lift":0.10,"contrast":0.78,"sat":0.90,"split":{"shadow":[0.0,0.02,0.03],"high":[0.03,0.02,0.0]}}),  # 舊調膠片
    ("primelive_dongri",      {"gain":[1.05,1.06,1.09],"bright":0.16,"contrast":0.72,"sat":0.98}),   # 冬日
    ("primelive_dongjing",    {"gain":[0.98,1.01,1.06],"bright":0.03,"contrast":1.07,"sat":1.02,"split":{"shadow":[0.0,0.02,0.04]}}),  # 東京
    ("primelive_jiepai",      {"gain":[1.04,1.02,1.02],"bright":0.04,"contrast":1.30,"sat":1.20}),   # 節拍
    ("primelive_heibai",      {"mono":True,"bright":0.06,"contrast":1.10,"mono_tint":[0.0,0.0,0.0]}),# 黑白
]

def write_cube(path, name, p):
    ramp = np.linspace(0, 1, SIZE, dtype=np.float32)
    # .cube 慣例:R 變化最快
    b, g, r = np.meshgrid(ramp, ramp, ramp, indexing="ij")
    grid = np.stack([r, g, b], -1).reshape(-1, 3)
    out = grade(grid, p)
    with open(path, "w", encoding="ascii") as f:
        f.write("TITLE \"%s\"\nLUT_3D_SIZE %d\n" % (name, SIZE))
        for px in out:
            f.write("%.6f %.6f %.6f\n" % (px[0], px[1], px[2]))

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, p in LOOKS:
        write_cube(os.path.join(OUT, name + ".cube"), name, p)
        print("寫出", name + ".cube")
    print("共 %d 款" % len(LOOKS))
