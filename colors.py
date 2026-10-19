"""Цвета и анимация цвета для Lottie."""
import colorsys
import copy
import re

NAMED = {
    "red": "#ff0000", "green": "#00c853", "blue": "#2962ff", "white": "#ffffff",
    "black": "#000000", "yellow": "#ffd600", "orange": "#ff9100", "purple": "#aa00ff",
    "pink": "#ff4081", "cyan": "#00e5ff", "gold": "#ffc107", "gray": "#9e9e9e",
    "красный": "#ff0000", "зелёный": "#00c853", "зеленый": "#00c853", "синий": "#2962ff",
    "белый": "#ffffff", "чёрный": "#000000", "черный": "#000000", "жёлтый": "#ffd600",
    "желтый": "#ffd600", "оранжевый": "#ff9100", "фиолетовый": "#aa00ff",
    "розовый": "#ff4081", "голубой": "#00e5ff", "золотой": "#ffc107", "серый": "#9e9e9e",
}
LIN = {"i": {"x": [1], "y": [1]}, "o": {"x": [0], "y": [0]}}


def parse_color(tok):
    t = NAMED.get(tok.strip().lower(), tok.strip().lower())
    m = re.fullmatch(r"#?([0-9a-f]{3}|[0-9a-f]{6})", t)
    if not m:
        raise ValueError(f"Не понял цвет «{tok}». Пример: #ff0000, #f00 или red")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(round(int(h[i:i + 2], 16) / 255, 4) for i in (0, 2, 4))


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in rgb)


def parse_spec(text):
    """'#f00' -> static; '#f00 #00f' -> cycle; 'grad #f00 #00f' -> grad; none; reset."""
    toks = text.replace(",", " ").split()
    if not toks:
        raise ValueError("Укажи цвет")
    w = toks[0].lower()
    if w in ("off", "reset", "сброс"):
        return {"mode": "reset", "colors": []}
    if w in ("none", "нет", "убрать"):
        return {"mode": "none", "colors": []}
    grad = w in ("grad", "gradient", "shimmer", "перелив")
    if grad:
        toks = toks[1:]
    cols = [parse_color(t) for t in toks]
    if not cols:
        raise ValueError("Укажи цвет")
    if grad:
        if len(cols) < 2:
            raise ValueError("Для перелива нужно минимум 2 цвета")
        return {"mode": "grad", "colors": cols}
    return {"mode": "cycle" if len(cols) > 1 else "static", "colors": cols}


def show_spec(spec):
    if not spec:
        return "как в оригинале"
    m, cols = spec["mode"], " ".join(to_hex(c) for c in spec["colors"])
    return {"none": "убрано", "static": cols, "cycle": f"смена: {cols}", "grad": f"перелив: {cols}"}[m]


def color_prop(spec, ip, op, cycles=1):
    """Свойство цвета: статичное или анимированное (плавная смена по кругу)."""
    cols = spec["colors"]
    if spec["mode"] == "static":
        return {"a": 0, "k": [*cols[0], 1]}
    n = len(cols)
    steps = n * max(1, int(cycles))
    kfs = []
    for i in range(steps + 1):
        kf = {"t": round(ip + (op - ip) * i / steps, 3), "s": [*cols[i % n], 1]}
        if i < steps:
            kf.update(copy.deepcopy(LIN))
        kfs.append(kf)
    return {"a": 1, "k": kfs}


def grad_item(spec, ip, op, cycles, bbox, stroke_w=None, nm="Text Fill"):
    """Градиент слева направо, цвета в стопах по кругу сдвигаются — «перелив»."""
    cols = spec["colors"]
    n = len(cols)
    x0, y0, x1, y1 = bbox
    cy = (y0 + y1) / 2

    def stops(shift):
        arr = []
        for i in range(n):
            arr += [round(i / (n - 1), 4), *cols[(i + shift) % n]]
        return arr

    steps = n * max(1, int(cycles))
    kfs = []
    for j in range(steps + 1):
        kf = {"t": round(ip + (op - ip) * j / steps, 3), "s": stops(j)}
        if j < steps:
            kf.update(copy.deepcopy(LIN))
        kfs.append(kf)
    item = {"ty": "gs" if stroke_w else "gf", "nm": nm, "o": {"a": 0, "k": 100}, "t": 1,
            "s": {"a": 0, "k": [round(x0, 2), round(cy, 2)]},
            "e": {"a": 0, "k": [round(x1, 2), round(cy, 2)]},
            "g": {"p": n, "k": {"a": 1, "k": kfs}}}
    if stroke_w:
        item.update({"w": {"a": 0, "k": stroke_w}, "lc": 1, "lj": 1})
    else:
        item["r"] = 1
    return item


def tint_gradient(g, rgb):
    """Перекрашивает градиент, сохраняя светотень (средняя яркость = яркость цвета)."""
    p = g.get("p", 0)
    k = g.get("k", {})
    if not p:
        return
    th, tl, ts = colorsys.rgb_to_hls(*rgb)

    def tint(arr):
        arr = list(arr)
        ls = [colorsys.rgb_to_hls(*arr[i * 4 + 1:i * 4 + 4])[1] for i in range(p)]
        mean = sum(ls) / p
        f = tl / mean if mean > 1e-6 else 1
        for i in range(p):
            r, gg, b = colorsys.hls_to_rgb(th, min(1, max(0, ls[i] * f)), ts)
            arr[i * 4 + 1:i * 4 + 4] = [round(r, 4), round(gg, 4), round(b, 4)]
        return arr

    if k.get("a") == 1:
        for kf in k.get("k", []):
            for key in ("s", "e"):
                if isinstance(kf.get(key), list):
                    kf[key] = tint(kf[key])
    elif isinstance(k.get("k"), list):
        k["k"] = tint(k["k"])
