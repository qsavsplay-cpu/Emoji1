"""Векторный текст в Lottie: глифы шрифта -> безье-пути."""
import gzip
import json

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

import lottie_ops as O


class Pen(BasePen):
    """Собирает контуры в формате Lottie-безье (в исходных единицах)."""

    def __init__(self, glyph_set=None):
        super().__init__(glyph_set)
        self.contours = []
        self._c = None

    def _moveTo(self, p):
        self._c = {"v": [list(p)], "i": [[0, 0]], "o": [[0, 0]], "c": True}

    def _lineTo(self, p):
        c = self._c
        c["v"].append(list(p)); c["i"].append([0, 0]); c["o"].append([0, 0])

    def _curveToOne(self, p1, p2, p3):
        c = self._c
        v = c["v"][-1]
        c["o"][-1] = [p1[0] - v[0], p1[1] - v[1]]
        c["v"].append(list(p3))
        c["i"].append([p2[0] - p3[0], p2[1] - p3[1]])
        c["o"].append([0, 0])

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
        c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
        self._curveToOne(c1, c2, p2)

    def _closePath(self):
        c = self._c
        if c is not None:
            if len(c["v"]) > 1 and c["v"][-1] == c["v"][0]:
                c["i"][0] = c["i"][-1]
                for k in ("v", "i", "o"):
                    c[k].pop()
            c["c"] = True
            self.contours.append(c)
        self._c = None

    def _endPath(self):
        c = self._c
        if c is not None:
            c["c"] = False
            self.contours.append(c)
        self._c = None


def _r(p, k=1.0, flip=False):
    return [round(p[0] * k, 2), round(p[1] * k * (-1 if flip else 1), 2)]


def build_glyph_shapes(text, font_path, size=80, max_width=None, center=(0, 0)):
    font = TTFont(font_path)
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    s = size / font["head"].unitsPerEm

    def adv(ch):
        return hmtx[cmap.get(ord(ch), ".notdef")][0] * s

    lines = text.split("\n")
    widths = [sum(adv(ch) for ch in ln) for ln in lines]
    if max_width and max(widths) > max_width:
        k = max_width / max(widths)
        s *= k; size *= k; widths = [w * k for w in widths]
    line_h = size * 1.2
    shapes = []
    for li, ln in enumerate(lines):
        x = center[0] - widths[li] / 2
        base_y = center[1] + (li - (len(lines) - 1) / 2) * line_h + size * 0.36
        for ch in ln:
            gn = cmap.get(ord(ch), ".notdef")
            if not ch.isspace():
                pen = Pen(gs)
                gs[gn].draw(pen)
                for c in pen.contours:
                    bez = {"c": True,
                           "v": [[round(x + v[0] * s, 2), round(base_y - v[1] * s, 2)] for v in c["v"]],
                           "i": [_r(t, s, True) for t in c["i"]],
                           "o": [_r(t, s, True) for t in c["o"]]}
                    shapes.append({"ty": "sh", "nm": "glyph", "ks": {"a": 0, "k": bez}})
            x += hmtx[gn][0] * s
    return shapes


def transform():
    return {"ty": "tr", "nm": "Transform",
            "p": {"a": 0, "k": [0, 0]}, "a": {"a": 0, "k": [0, 0]},
            "s": {"a": 0, "k": [100, 100]}, "r": {"a": 0, "k": 0},
            "o": {"a": 0, "k": 100}, "sk": {"a": 0, "k": 0}, "sa": {"a": 0, "k": 0}}


def _fill(rgb):
    return {"ty": "fl", "nm": "Fill", "r": 1, "o": {"a": 0, "k": 100}, "c": {"a": 0, "k": [*rgb, 1]}}


def _first_fill_color(node):
    if isinstance(node, dict):
        if node.get("ty") == "fl":
            k = node.get("c", {}).get("k")
            if isinstance(k, list) and len(k) >= 3 and isinstance(k[0], (int, float)):
                return tuple(k[:3])
        for v in node.values():
            r = _first_fill_color(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _first_fill_color(v)
            if r:
                return r
    return None


def replace_text(lottie, name, text, font_path, size=80, max_width=None):
    """Очищает найденные слои/папки и вставляет векторный текст.
    max_width: None = как у прежнего содержимого, 0 = без ограничения.
    Возвращает список {container, parent, bbox}."""
    found = []
    O.find_nodes(lottie, [name], found)
    results = []
    for node, parent in found:
        if node.get("ty") == "gr":
            old = node.get("it", [])
            bb = O.path_bbox(old)
            center, w = (0, 0), None
            if bb:
                center, w = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2), bb[2] - bb[0]
            mw = w if max_width is None else (max_width or None)
            shapes = build_glyph_shapes(text, font_path, size, mw, center)
            styles = [i for i in old if i.get("ty") in ("fl", "st", "gf", "gs")] or [_fill((1, 1, 1))]
            tr = next((i for i in old if i.get("ty") == "tr"), transform())
            node["it"] = [*shapes, *styles, tr]
            results.append({"container": node, "parent": parent, "bbox": O.path_bbox(shapes)})
        else:  # слой shape/text -> шейп-слой
            color = _first_fill_color(node) or (1, 1, 1)
            shapes = build_glyph_shapes(text, font_path, size, max_width or None)
            grp = {"ty": "gr", "nm": "text_vector", "it": [*shapes, _fill(color), transform()]}
            node["ty"] = 4
            node.pop("t", None)
            node["shapes"] = [grp]
            results.append({"container": grp, "parent": node["shapes"], "bbox": O.path_bbox(shapes)})
    return results


def load(data: bytes):
    try:
        data = gzip.decompress(data)
    except OSError:
        pass
    return json.loads(data.decode("utf-8"))


def to_tgs(lottie) -> bytes:
    raw = json.dumps(lottie, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return gzip.compress(raw, 9)
