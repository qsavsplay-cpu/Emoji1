"""Поиск, удаление, перекраска, структура Lottie."""
import fnmatch

from colors import tint_gradient

LAYER_TYPES = (0, 1, 2, 3, 4, 5, "gr")
TYPE_NAMES = {0: "precomp", 1: "solid", 2: "image", 3: "null", 4: "shape", 5: "text", "gr": "папка"}


def matches(node, patterns):
    if not patterns or not isinstance(node, dict) or node.get("ty") not in LAYER_TYPES:
        return False
    nm = str(node.get("nm", "")).lower()
    return any(fnmatch.fnmatchcase(nm, p.lower()) for p in patterns)


def find_nodes(node, patterns, out, parent=None):
    """Собирает (узел, список-родитель) для слоёв/папок, чьё имя подходит под patterns."""
    if isinstance(node, dict):
        if matches(node, patterns):
            out.append((node, parent))
        for v in node.values():
            find_nodes(v, patterns, out, None)
    elif isinstance(node, list):
        for v in node:
            find_nodes(v, patterns, out, node)


def remove_nodes(root, patterns, protect=()):
    found = []
    find_nodes(root, patterns, found)
    n = 0
    for node, parent in found:
        if parent is None or matches(node, protect):
            continue
        for i, x in enumerate(parent):
            if x is node:
                del parent[i]
                n += 1
                break
    return n


def recolor(root, fill=None, stroke=None, skip=()):
    """fill/stroke — rgb-кортежи. Сплошные заливки/обводки красятся точно,
    градиенты — с сохранением светотени. Узлы из skip не трогаются."""
    cnt = [0]

    def rec(node):
        if isinstance(node, dict):
            if matches(node, skip):
                return
            ty = node.get("ty")
            if fill and ty == "fl":
                node["c"] = {"a": 0, "k": [*fill, 1]}; cnt[0] += 1
            elif fill and ty == "gf":
                tint_gradient(node.get("g", {}), fill); cnt[0] += 1
            elif stroke and ty == "st":
                node["c"] = {"a": 0, "k": [*stroke, 1]}; cnt[0] += 1
            elif stroke and ty == "gs":
                tint_gradient(node.get("g", {}), stroke); cnt[0] += 1
            for v in node.values():
                rec(v)
        elif isinstance(node, list):
            for v in node:
                rec(v)

    rec(root)
    return cnt[0]


def tree(root, max_depth=5):
    lines = []

    def shapes(items, depth):
        for it in items:
            if isinstance(it, dict) and it.get("ty") == "gr":
                lines.append("  " * depth + f"📁 {it.get('nm')}")
                if depth < max_depth:
                    shapes(it.get("it", []), depth + 1)

    def layers(ls, depth):
        for l in ls:
            lines.append("  " * depth + f"▪ [{TYPE_NAMES.get(l.get('ty'), l.get('ty'))}] {l.get('nm')}")
            shapes(l.get("shapes", []), depth + 1)

    layers(root.get("layers", []), 0)
    for a in root.get("assets", []):
        if "layers" in a:
            lines.append(f"\n== precomp {a.get('id')} ==")
            layers(a["layers"], 0)
    return "\n".join(lines)


def static_val(prop, default):
    if not isinstance(prop, dict):
        return default
    k = prop.get("k")
    if prop.get("a") == 1 and isinstance(k, list) and k and isinstance(k[0], dict):
        s = k[0].get("s")
        return s if s is not None else default
    return k if k is not None else default


def to_parent(tr, bbox):
    """bbox внутри папки -> bbox в координатах её родителя (по трансформу папки)."""
    p = static_val(tr.get("p"), [0, 0]); a = static_val(tr.get("a"), [0, 0])
    s = static_val(tr.get("s"), [100, 100])

    def f(x, y):
        return (p[0] + (x - a[0]) * s[0] / 100, p[1] + (y - a[1]) * s[1] / 100)

    (x0, y0), (x1, y1) = f(bbox[0], bbox[1]), f(bbox[2], bbox[3])
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def path_bbox(node):
    """Границы статических путей внутри node или None."""
    pts = []

    def rec(n):
        if isinstance(n, dict):
            if n.get("ty") == "sh" and n.get("ks", {}).get("a") == 0:
                pts.extend(n["ks"]["k"].get("v", []))
            for v in n.values():
                rec(v)
        elif isinstance(n, list):
            for v in n:
                rec(v)

    rec(node)
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)
