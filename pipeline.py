"""Сборка результата: удаление → перекраска → текст → стиль текста → лого."""
import copy

import colors as C
import lottie_ops as O
import lottie_text as T
import svgimport as S

DEFAULTS = dict(
    layer="EMOJI", size=80, width=None, font=None,
    remove=[], autologo=True, skip=[], fill=None, stroke=None,
    text_fill=None, text_stroke=None, stroke_w=None, cycles=1,
    logo_size=90, logo_pos="left", logo_dx=0, logo_dy=0, logo_color=None, logo_slot="LOGO",
)


def _static_rgb(spec):
    return spec["colors"][0] if spec and spec["mode"] == "static" else None


def _num(prop, d):
    v = O.static_val(prop, d)
    return v[0] if isinstance(v, list) else v


def _style_text(r, s, ip, op):
    node = r["container"]
    it = node["it"]
    shapes = [i for i in it if i.get("ty") == "sh"]
    fills = [i for i in it if i.get("ty") in ("fl", "gf")]
    strokes = [i for i in it if i.get("ty") in ("st", "gs")]
    tr = next(i for i in it if i.get("ty") == "tr")
    bbox = r["bbox"] or (-50, -20, 50, 20)
    width = s["stroke_w"] or (_num(strokes[0].get("w"), 3) if strokes else 3)

    spec = s["text_fill"]
    if spec:
        if spec["mode"] == "none":
            fills = []
        elif spec["mode"] == "grad":
            fills = [C.grad_item(spec, ip, op, s["cycles"], bbox, nm="Text Fill")]
        else:
            fills = [{"ty": "fl", "nm": "Text Fill", "r": 1, "o": {"a": 0, "k": 100},
                      "c": C.color_prop(spec, ip, op, s["cycles"])}]
    spec = s["text_stroke"]
    if spec:
        if spec["mode"] == "none":
            strokes = []
        elif spec["mode"] == "grad":
            strokes = [C.grad_item(spec, ip, op, s["cycles"], bbox, stroke_w=width, nm="Text Stroke")]
        else:
            strokes = [{"ty": "st", "nm": "Text Stroke", "o": {"a": 0, "k": 100}, "lj": 1, "lc": 1,
                        "w": {"a": 0, "k": width}, "c": C.color_prop(spec, ip, op, s["cycles"])}]
    elif s["stroke_w"] and strokes:
        for st in strokes:
            st["w"] = {"a": 0, "k": width}
    node["it"] = [*shapes, *fills, *strokes, tr]


def _logo_group(svg, s):
    return S.svg_to_group(svg, s["logo_size"], _static_rgb(s["logo_color"]))


def _logo_into_slot(data, s, svg):
    found = []
    O.find_nodes(data, [s["logo_slot"]], found)
    n = 0
    for node, _ in found:
        if node.get("ty") != "gr":
            continue
        bb = O.path_bbox(node.get("it", []))
        dim = max(bb[2] - bb[0], bb[3] - bb[1]) if bb else s["logo_size"]
        grp, _ = S.svg_to_group(svg, dim or s["logo_size"], _static_rgb(s["logo_color"]))
        if bb:
            grp["it"][-1]["p"]["k"] = [round((bb[0] + bb[2]) / 2, 2), round((bb[1] + bb[3]) / 2, 2)]
        tr = next((i for i in node.get("it", []) if i.get("ty") == "tr"), T.transform())
        node["it"] = [grp, tr]
        n += 1
    return n


def _logo_beside(r, s, svg):
    if r["parent"] is None:
        return False
    grp, (lw, lh) = _logo_group(svg, s)
    tr = next(i for i in r["container"]["it"] if i.get("ty") == "tr")
    x0, y0, x1, y1 = O.to_parent(tr, r["bbox"])
    cx, cy, gap, pos = (x0 + x1) / 2, (y0 + y1) / 2, 10, s["logo_pos"]
    x, y = {"left": (x0 - gap - lw / 2, cy), "right": (x1 + gap + lw / 2, cy),
            "above": (cx, y0 - gap - lh / 2), "below": (cx, y1 + gap + lh / 2)}.get(pos, (cx, cy))
    grp["it"][-1]["p"]["k"] = [round(x + s["logo_dx"], 2), round(y + s["logo_dy"], 2)]
    r["parent"].insert(0, grp)
    return True


def render(lottie, s, text, font_path, logo_svg=None):
    data = copy.deepcopy(lottie)
    ip, op = data.get("ip", 0), data.get("op", 60)
    rep = {"removed": 0, "recolored": 0, "text": 0, "logo": 0}

    slot = _logo_into_slot(data, s, logo_svg) if logo_svg else 0
    pats = list(s["remove"]) + (["*logo*", "*лого*"] if s["autologo"] else [])
    if pats:
        rep["removed"] = O.remove_nodes(data, pats, protect=[s["logo_slot"]] if slot else [])

    fill, stroke = _static_rgb(s["fill"]), _static_rgb(s["stroke"])
    if fill or stroke:
        rep["recolored"] = O.recolor(data, fill, stroke, skip=[s["layer"], s["logo_slot"], *s["skip"]])

    res = T.replace_text(data, s["layer"], text, font_path, s["size"], s["width"])
    rep["text"] = len(res)
    for r in res:
        _style_text(r, s, ip, op)
    if logo_svg:
        rep["logo"] = slot or sum(_logo_beside(r, s, logo_svg) for r in res)
    return data, rep
