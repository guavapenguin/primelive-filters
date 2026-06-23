"""primelive 文青/感性氛圍 調色 LUT 產生器。
產生 6 個 .cube 到 ../assets/luts/，對應「氛圍」濾鏡類別（OBS 套用 LUT，一檔一按鈕）。
品牌調性：文青、感性、知性療癒、SFW。要微調就改下方參數再重跑：python make_ambiance_luts.py
"""
import os

N = 33
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "luts")


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def process(r, g, b, p):
    r *= p["temp"][0]; g *= p["temp"][1]; b *= p["temp"][2]
    r, g, b = clamp(r), clamp(g), clamp(b)
    out = []
    for c in (r, g, b):
        c = clamp(c * p["gain"] + p["lift"])
        c = c ** (1.0 / p["gamma"])
        out.append(c)
    r, g, b = out
    k = p["contrast"]
    r = clamp(0.5 + (r - 0.5) * k); g = clamp(0.5 + (g - 0.5) * k); b = clamp(0.5 + (b - 0.5) * k)
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    s = p["sat"]
    r = clamp(luma + (r - luma) * s); g = clamp(luma + (g - luma) * s); b = clamp(luma + (b - luma) * s)
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    sw = 1.0 - luma; hw = luma
    st = p["shadow_tint"]; ht = p["high_tint"]; ss = p["split_strength"]
    r = clamp(r + (st[0] * sw + ht[0] * hw) * ss)
    g = clamp(g + (st[1] * sw + ht[1] * hw) * ss)
    b = clamp(b + (st[2] * sw + ht[2] * hw) * ss)
    return r, g, b


def write_lut(path, title, p):
    out = ['TITLE "%s"' % title, "LUT_3D_SIZE %d" % N, "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    d = N - 1
    for bi in range(N):
        for gi in range(N):
            for ri in range(N):
                r, g, b = process(ri / d, gi / d, bi / d, p)
                out.append("%.6f %.6f %.6f" % (r, g, b))
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(out) + "\n")
    print("wrote", path)


PRESETS = {
    # 奶茶暖陽：奶油暖調、柔和提亮，最百搭的文青基底
    "milktea_warm": {"temp": (1.04, 1.005, 0.95), "lift": 0.02, "gamma": 1.08, "gain": 0.98,
                      "contrast": 0.96, "sat": 1.03, "shadow_tint": (0.5, 0.2, 0.0),
                      "high_tint": (0.6, 0.4, 0.1), "split_strength": 0.045, "title": "Milktea Warm"},
    # 底片灰調：去飽和、褪色、低對比，安靜文藝
    "film_muted": {"temp": (1.01, 1.0, 0.99), "lift": 0.035, "gamma": 1.04, "gain": 0.95,
                    "contrast": 0.9, "sat": 0.84, "shadow_tint": (0.0, 0.3, 0.2),
                    "high_tint": (0.3, 0.3, 0.2), "split_strength": 0.04, "title": "Film Muted"},
    # 陰雨藍灰：冷靜、藍灰陰影，適合下雨天/深夜談心
    "rainy_bluegrey": {"temp": (0.97, 1.0, 1.04), "lift": 0.025, "gamma": 1.03, "gain": 0.97,
                        "contrast": 0.98, "sat": 0.9, "shadow_tint": (-0.2, 0.1, 0.5),
                        "high_tint": (0.0, 0.1, 0.3), "split_strength": 0.05, "title": "Rainy Blue-Grey"},
    # 童話柔光：明亮粉嫩、夢幻提亮，溫柔可愛
    "fairytale_soft": {"temp": (1.035, 1.0, 0.97), "lift": 0.045, "gamma": 1.15, "gain": 0.97,
                        "contrast": 0.9, "sat": 1.05, "shadow_tint": (0.4, 0.1, 0.3),
                        "high_tint": (0.6, 0.35, 0.3), "split_strength": 0.05, "title": "Fairytale Soft"},
    # 夜晚暖燈：琥珀高光、深邃陰影，居家夜談氛圍
    "night_lamp": {"temp": (1.05, 1.0, 0.93), "lift": 0.0, "gamma": 0.98, "gain": 1.0,
                   "contrast": 1.06, "sat": 1.0, "shadow_tint": (-0.1, 0.0, 0.4),
                   "high_tint": (0.7, 0.4, 0.0), "split_strength": 0.05, "title": "Night Lamp"},
    # 日系清新：明亮通透、微冷中性、乾淨膚色
    "jp_fresh": {"temp": (0.995, 1.0, 1.015), "lift": 0.03, "gamma": 1.12, "gain": 0.98,
                 "contrast": 0.95, "sat": 0.97, "shadow_tint": (0.0, 0.2, 0.3),
                 "high_tint": (0.2, 0.3, 0.3), "split_strength": 0.035, "title": "JP Fresh"},
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for key, p in PRESETS.items():
        write_lut(os.path.join(OUT, "primelive_amb_%s.cube" % key), "primelive " + p["title"], p)
    print("done ->", OUT)
