"""SVG -> векторная группа Lottie (для лого). Растровые картинки в TGS нельзя."""
import math
import re
import xml.etree.ElementTree as ET

from fontTools.svgLib.path import parse_path

from colors import parse_color
from lottie_text import Pen, transform

SKIP = {"defs", "clippath", "mask", "symbol", "style", "title", "desc", "metadata",
        "lineargradient", "radialgradient", "pattern", "filter"}


def _tag(el):
    return el.tag.split("}")[-1].lower()


def _num(s, d=0.0):
    try:
        return float(re.sub(r"[a-zA-Z%]+$", "", str(s).strip()))
    except (TypeError, ValueError):
        return d


def _mul(m, n):
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def _parse_tf(s):
    m = (1, 0, 0, 1, 0, 0)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate":
            r = math.radians(v[0]); c, sn = math.cos(r), math.sin(r)
            t = (c, sn, -sn, c, 0, 0)
            if len(v) == 3:
                t = _mul(_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "matrix" and len(v) == 6:
            t = tuple(v)
        else:
            continue
        m = _mul(m, t)
    return m


def _style(el):
    d = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            d[k.strip()] = v.strip()
    for k in ("fill", "stroke", "stroke-width", "fill-opacity", "stroke-opacity", "fill-rule"):
        if el.get(k) is not None and k not in d:
            d[k] = el.get(k)
    return d


def _color(v, ids):
    if v is None:
        return None
    v = v.strip()
    low = v.lower()
    if low in ("none", "transparent"):
        return None
    if low == "currentcolor":
        return (0, 0, 0)
    if low.startswith("url("):
        ref = ids.get(low[low.find("#") + 1:low.rfind(")")])
        if ref is not None:
            for st in ref.iter():
                if _tag(st) == "stop":
                    c = _style(st).get("stop-color") or st.get("stop-color")
                    if not c:
                        for part in (st.get("style") or "").split(";"):
                            if part.strip().startswith("stop-color"):
                                c = part.split(":")[1]
                    if c:
                        return _color(c, ids)
        return (0.5, 0.5, 0.5)
    m = re.fullmatch(r"rgba?\(([^)]*)\)", low)
    if m:
        p = [x for x in re.split(r"[\s,/]+", m.group(1).strip()) if x][:3]
        return tuple(round(min(255, _num(x) * (2.55 if x.endswith("%") else 1)) / 255, 4) for x in p)
    try:
        return parse_color(v)
    except ValueError:
        return (0, 0, 0)


def _shape_d(el):
    t = _tag(el)
    g = lambda k: _num(el.get(k, 0))
    if t == "path":
        return el.get("d")
    if t == "rect":
        x, y, w, h = g("x"), g("y"), g("width"), g("height")
        return f"M{x} {y}H{x + w}V{y + h}H{x}Z" if w and h else None
    if t in ("circle", "ellipse"):
        cx, cy = g("cx"), g("cy")
        rx = g("r") if t == "circle" else g("rx")
        ry = rx if t == "circle" else g("ry")
        if not rx or not ry:
            return None
        return f"M{cx - rx} {cy}A{rx} {ry} 0 1 0 {cx + rx} {cy}A{rx} {ry} 0 1 0 {cx - rx} {cy}Z"
    if t == "line":
        return f"M{g('x1')} {g('y1')}L{g('x2')} {g('y2')}"
    if t in ("polygon", "polyline"):
        n = [float(x) for x in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", el.get("points", ""))]
        if len(n) < 4:
            return None
        d = f"M{n[0]} {n[1]}" + "".join(f"L{n[i]} {n[i + 1]}" for i in range(2, len(n) - 1, 2))
        return d + ("Z" if t == "polygon" else "")
    return None


def svg_to_group(data: bytes, size=90, override=None):
    """Возвращает (группа Lottie, (ширина, высота) после масштабирования до size)."""
    root = ET.fromstring(data)
    ids = {el.get("id"): el for el in root.iter() if el.get("id")}
    items = []

    def visit(el, inh, m):
        if _tag(el) in SKIP:
            return
        st = dict(inh)
        st.update(_style(el))
        m = _mul(m, _parse_tf(el.get("transform")))
        d = _shape_d(el)
        if d:
            try:
                pen = Pen()
                parse_path(d, pen)
                if pen._c is not None:
                    pen._endPath()
                a, b, c, dd, e, f = m
                cs = []
                for k in pen.contours:
                    cs.append({
                        "c": k["c"],
                        "v": [[a * x + c * y + e, b * x + dd * y + f] for x, y in k["v"]],
                        "i": [[a * x + c * y, b * x + dd * y] for x, y in k["i"]],
                        "o": [[a * x + c * y, b * x + dd * y] for x, y in k["o"]]})
                if cs:
                    items.append((cs, st, math.sqrt(abs(a * dd - b * c)) or 1))
            except Exception:
                pass
        for ch in el:
            visit(ch, st, m)

    visit(root, {"fill": "#000000"}, (1, 0, 0, 1, 0, 0))
    if not items:
        raise ValueError("В SVG не нашёл векторных фигур (path/rect/circle/polygon…)")

    xs = [v[0] for cs, _, _ in items for k in cs for v in k["v"]]
    ys = [v[1] for cs, _, _ in items for k in cs for v in k["v"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)

    parts = []
    for cs, st, scale in items:
        shapes = [{"ty": "sh", "nm": "path", "ks": {"a": 0, "k": {
            "c": k["c"],
            "v": [[round(p[0], 2), round(p[1], 2)] for p in k["v"]],
            "i": [[round(p[0], 2), round(p[1], 2)] for p in k["i"]],
            "o": [[round(p[0], 2), round(p[1], 2)] for p in k["o"]]}}} for k in cs]
        fill = override or _color(st.get("fill"), ids)
        stroke = override or _color(st.get("stroke"), ids)
        it = list(shapes)
        if fill:
            it.append({"ty": "fl", "nm": "Fill", "o": {"a": 0, "k": round(_num(st.get("fill-opacity", 1), 1) * 100)},
                       "r": 2 if st.get("fill-rule") == "evenodd" else 1,
                       "c": {"a": 0, "k": [*fill, 1]}})
        if stroke:
            it.append({"ty": "st", "nm": "Stroke", "o": {"a": 0, "k": round(_num(st.get("stroke-opacity", 1), 1) * 100)},
                       "w": {"a": 0, "k": round(_num(st.get("stroke-width", 1), 1) * scale, 2)},
                       "lc": 2, "lj": 2, "c": {"a": 0, "k": [*stroke, 1]}})
        if fill or stroke:
            it.append(transform())
            parts.append({"ty": "gr", "nm": "badge part", "it": it})

    k = size / max(w, h)
    tr = transform()
    tr["a"]["k"] = [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)]
    tr["s"]["k"] = [round(k * 100, 3)] * 2
    return {"ty": "gr", "nm": "badge", "it": [*parts, tr]}, (w * k, h * k)
