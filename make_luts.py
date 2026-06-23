"""primelive 調色 LUT 產生器。
產生兩個 .cube 到 ./luts/：女款（暖膚柔光）、男款（冷峻清晰）。
要換色調就改下方 female / male 的參數再重跑：  python make_luts.py
"""
import os

N = 33
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "luts")


def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def process(r, g, b, p):
    # 1. 色溫 / 白平衡
    r *= p["temp"][0]; g *= p["temp"][1]; b *= p["temp"][2]
    r, g, b = clamp(r), clamp(g), clamp(b)
    # 2. lift / gamma / gain
    out = []
    for c in (r, g, b):
        c = clamp(c * p["gain"] + p["lift"])
        c = c ** (1.0 / p["gamma"])
        out.append(c)
    r, g, b = out
    # 3. 對比（繞 0.5）
    k = p["contrast"]
    r = clamp(0.5 + (r - 0.5) * k); g = clamp(0.5 + (g - 0.5) * k); b = clamp(0.5 + (b - 0.5) * k)
    # 4. 飽和
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    s = p["sat"]
    r = clamp(luma + (r - luma) * s); g = clamp(luma + (g - luma) * s); b = clamp(luma + (b - luma) * s)
    # 5. 分離色調（陰影 vs 高光）
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    sw = 1.0 - luma; hw = luma
    st = p["shadow_tint"]; ht = p["high_tint"]; ss = p["split_strength"]
    r = clamp(r + (st[0] * sw + ht[0] * hw) * ss)
    g = clamp(g + (st[1] * sw + ht[1] * hw) * ss)
    b = clamp(b + (st[2] * sw + ht[2] * hw) * ss)
    return r, g, b


def write_lut(path, title, p):
    out = ['TITLE "%s"' % title, "LUT_3D_SIZE %d" % N,
           "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    d = N - 1
    for bi in range(N):
        for gi in range(N):
            for ri in range(N):
                r, g, b = process(ri / d, gi / d, bi / d, p)
                out.append("%.6f %.6f %.6f" % (r, g, b))
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(out) + "\n")
    print("wrote", path)


# 女款：暖膚、提亮、微粉柔光
female = {"temp": (1.04, 1.005, 0.955), "lift": 0.015, "gamma": 1.12, "gain": 0.98,
          "contrast": 0.94, "sat": 1.08, "shadow_tint": (0.6, 0.0, 0.4),
          "high_tint": (0.6, 0.3, 0.0), "split_strength": 0.05}
# 男款：冷峻、對比、輪廓清晰（青橙分離）
male = {"temp": (0.985, 1.0, 1.03), "lift": 0.0, "gamma": 0.97, "gain": 1.0,
        "contrast": 1.12, "sat": 0.95, "shadow_tint": (-0.3, 0.1, 0.5),
        "high_tint": (0.5, 0.25, -0.2), "split_strength": 0.05}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    write_lut(os.path.join(OUT, "primelive_LUT_female_warm.cube"), "primelive Female Warm Soft", female)
    write_lut(os.path.join(OUT, "primelive_LUT_male_clarity.cube"), "primelive Male Clarity", male)
    print("done ->", OUT)
