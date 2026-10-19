import copy
import io
import json
import logging
import os
from pathlib import Path

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import colors as C
import lottie_ops as O
import lottie_text as T
import pipeline as P
import svgimport as SVG

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("Не задана переменная BOT_TOKEN (Railway → Variables)")

BASE = Path(__file__).parent
FONTS, TPL = BASE / "fonts", BASE / "templates"
ASK = "✏️ На какой текст заменить?"
logging.basicConfig(level=logging.INFO)

HELP = """Как работать:
1) /templates — выбрать заготовку эмодзи (или пришли свой .json / .tgs / анимированный стикер)
2) Напиши текст — получишь .tgs. Подпись к файлу = сразу текст.
После любой настройки жми /go — пересоберу с прошлым текстом.

ТЕКСТ: /size 80 · /width auto|число|0 · /font · /layer имя
ЦВЕТ ТЕКСТА (/textfill — заливка, /textstroke — контур, /strokew — толщина):
 • один цвет: /textfill #ff0000
 • плавная смена: /textfill #ff0000 #0000ff
 • перелив (градиент): /textfill grad #ff0000 #ffff00 #00ff00
 • none — убрать, off — как в оригинале; /cycles 2 — циклов за анимацию
ЦВЕТ ЭМОДЗИ (заливка и контур отдельно): /fill #hex · /stroke #hex · /skip глаза* (не красить)
УДАЛЕНИЕ: /remove имя* · /remove clear · /autologo on|off (удалять всё с «logo/лого») · /tree — структура файла
ЛОГО: пришли .svg · /logo off · /logopos left|right|above|below|center [dx dy] · /logosize 90 · /logocolor #hex|off
(лого только векторное: PNG/JPG в TGS нельзя)
/settings · /reset"""


def fonts_list():
    return sorted(p.name for p in FONTS.glob("*.[to]tf"))


def templates():
    p = TPL / "index.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def S(ctx):
    s = ctx.user_data.setdefault("s", copy.deepcopy(P.DEFAULTS))
    if not s.get("font"):
        fl = fonts_list()
        s["font"] = fl[0] if fl else None
    return s


async def reply(u, text, **kw):
    await u.effective_message.reply_text(text, **kw)


async def start(u, ctx):
    await reply(u, HELP)


# ---------- рендер ----------
async def render(u, ctx, text):
    ud, s = ctx.user_data, S(ctx)
    if "lottie" not in ud:
        return await reply(u, "Сначала выбери /templates или пришли .json/.tgs")
    if not s["font"]:
        return await reply(u, "Положи .ttf шрифт (с кириллицей) в папку fonts/")
    ud["last_text"] = text
    try:
        data, rep = P.render(ud["lottie"], s, text, FONTS / s["font"], ud.get("logo"))
    except Exception as e:
        logging.exception("render failed")
        return await reply(u, f"Ошибка при сборке: {e}")
    if not rep["text"]:
        return await reply(u, f"Слой/папка «{s['layer']}» не найден(а). Посмотри /tree и задай /layer имя")
    tgs = T.to_tgs(data)
    cap = [f"Готово: «{text}»"]
    if rep["removed"]:
        cap.append(f"удалено: {rep['removed']}")
    if rep["recolored"]:
        cap.append(f"перекрашено: {rep['recolored']}")
    if ud.get("logo") and not rep["logo"]:
        cap.append("лого не добавилось")
    elif rep["logo"]:
        cap.append("лого добавлено")
    if len(tgs) > 64 * 1024:
        cap.append(f"⚠️ {len(tgs) // 1024} КБ — лимит стикера 64 КБ")
    await u.effective_message.reply_document(io.BytesIO(tgs), filename="result.tgs", caption=" · ".join(cap))
    await reply(u, ASK + "\n(или /go после настроек, или пришли новый файл)",
                reply_markup=ForceReply(selective=True))


async def go(u, ctx):
    if "last_text" not in ctx.user_data:
        return await reply(u, "Сначала пришли текст")
    await render(u, ctx, ctx.user_data["last_text"])


# ---------- файлы ----------
async def load_animation(u, ctx, obj, caption):
    buf = io.BytesIO()
    await (await obj.get_file()).download_to_memory(buf)
    try:
        ctx.user_data["lottie"] = T.load(buf.getvalue())
    except Exception as e:
        return await reply(u, f"Не смог прочитать анимацию: {e}")
    if caption:
        return await render(u, ctx, caption)
    await reply(u, ASK, reply_markup=ForceReply(selective=True))


async def on_file(u, ctx):
    m = u.message
    if m.sticker:
        return await load_animation(u, ctx, m.sticker, m.caption)
    name = m.document.file_name.lower()
    if name.endswith((".json", ".tgs")):
        return await load_animation(u, ctx, m.document, m.caption)
    if name.endswith(".svg"):
        buf = io.BytesIO()
        await (await m.document.get_file()).download_to_memory(buf)
        try:
            SVG.svg_to_group(buf.getvalue(), 90)
        except Exception as e:
            return await reply(u, f"Не получилось прочитать SVG: {e}")
        ctx.user_data["logo"] = buf.getvalue()
        return await reply(u, "Лого сохранено ✅ Позиция: /logopos, размер: /logosize. Жми /go")
    await reply(u, "Нужен .json / .tgs (анимация) или .svg (лого). PNG/JPG в TGS вставить нельзя — только вектор.")


async def on_photo(u, ctx):
    await reply(u, "Растровые картинки в TGS нельзя. Пришли лого как .svg (файлом).")


async def on_text(u, ctx):
    await render(u, ctx, u.message.text)


# ---------- шаблоны ----------
async def tpl_list(u, ctx):
    t = templates()
    if not t:
        return await reply(u, "Шаблонов нет. Пришли свой .json/.tgs")
    kb = [[InlineKeyboardButton(v.get("title", k), callback_data=f"tpl:{k}")] for k, v in t.items()]
    await reply(u, "Выбери эмодзи:", reply_markup=InlineKeyboardMarkup(kb))


def apply_template(ctx, key):
    t = templates().get(key)
    if not t:
        return False
    ctx.user_data["lottie"] = T.load((TPL / t["file"]).read_bytes())
    ctx.user_data["s"] = copy.deepcopy(P.DEFAULTS) | t.get("settings", {})
    return True


async def on_tpl(u, ctx):
    q = u.callback_query
    await q.answer()
    if not apply_template(ctx, q.data[4:]):
        return await q.message.reply_text("Шаблон не найден")
    await q.message.reply_text("Шаблон загружен. " + ASK, reply_markup=ForceReply(selective=True))


async def use(u, ctx):
    if ctx.args and apply_template(ctx, ctx.args[0]):
        return await reply(u, "Шаблон загружен. " + ASK, reply_markup=ForceReply(selective=True))
    await reply(u, "Список: /templates")


# ---------- настройки ----------
def make_spec_cmd(key, label, only_static=False):
    async def cmd(u, ctx):
        s = S(ctx)
        if not ctx.args:
            return await reply(u, f"{label}: {C.show_spec(s[key])}")
        try:
            spec = C.parse_spec(" ".join(ctx.args))
        except ValueError as e:
            return await reply(u, str(e))
        if only_static and spec["mode"] not in ("static", "reset"):
            return await reply(u, "Для эмодзи нужен один цвет (или off — как в оригинале).")
        s[key] = None if spec["mode"] == "reset" else spec
        await reply(u, f"{label}: {C.show_spec(s[key])}  → /go")
    return cmd


def make_num_cmd(key, label, cast=float, allow_auto=False):
    async def cmd(u, ctx):
        s = S(ctx)
        if ctx.args:
            a = ctx.args[0].lower()
            if allow_auto and a == "auto":
                s[key] = None
            else:
                try:
                    s[key] = cast(a)
                except ValueError:
                    return await reply(u, "Нужно число")
        v = s[key]
        await reply(u, f"{label}: {'auto (как у прежнего текста)' if v is None else v}  → /go")
    return cmd


async def set_layer(u, ctx):
    if ctx.args:
        S(ctx)["layer"] = " ".join(ctx.args)
    await reply(u, f"Слой/папка с текстом: {S(ctx)['layer']}")


async def set_font(u, ctx):
    s = S(ctx)
    if ctx.args and ctx.args[0] in fonts_list():
        s["font"] = ctx.args[0]
    await reply(u, f"Шрифт: {s['font']}\nДоступные: {', '.join(fonts_list()) or 'нет — положи .ttf в fonts/'}")


async def set_skip(u, ctx):
    s = S(ctx)
    if ctx.args:
        s["skip"] = [] if ctx.args[0] == "clear" else list(ctx.args)
    await reply(u, f"Не красить: {', '.join(s['skip']) or '—'}  → /go")


async def set_remove(u, ctx):
    s = S(ctx)
    if ctx.args:
        s["remove"] = [] if ctx.args[0] == "clear" else list(ctx.args)
    await reply(u, f"Удалять: {', '.join(s['remove']) or '—'} (* — любая часть имени)  → /go")


async def set_autologo(u, ctx):
    s = S(ctx)
    if ctx.args:
        s["autologo"] = ctx.args[0].lower() in ("on", "1", "да", "вкл")
    await reply(u, f"Авто-удаление «logo/лого»: {'вкл' if s['autologo'] else 'выкл'}")


async def logo_cmd(u, ctx):
    if ctx.args and ctx.args[0] == "off":
        ctx.user_data.pop("logo", None)
        return await reply(u, "Лого убрано")
    await reply(u, "Пришли лого файлом .svg" + (" (текущее заменится)" if ctx.user_data.get("logo") else ""))


async def logopos(u, ctx):
    s = S(ctx)
    if ctx.args and ctx.args[0] in ("left", "right", "above", "below", "center"):
        s["logo_pos"] = ctx.args[0]
        try:
            s["logo_dx"] = float(ctx.args[1]) if len(ctx.args) > 1 else 0
            s["logo_dy"] = float(ctx.args[2]) if len(ctx.args) > 2 else 0
        except ValueError:
            pass
    await reply(u, f"Лого: {s['logo_pos']}, сдвиг {s['logo_dx']}/{s['logo_dy']}  → /go")


async def tree(u, ctx):
    if "lottie" not in ctx.user_data:
        return await reply(u, "Сначала загрузи анимацию")
    txt = O.tree(ctx.user_data["lottie"])
    if len(txt) < 3500:
        return await reply(u, txt)
    await u.effective_message.reply_document(io.BytesIO(txt.encode()), filename="tree.txt",
                                             caption="Слои и папки (имена для /layer, /remove, /skip)")


async def settings(u, ctx):
    s = S(ctx)
    await reply(u, "\n".join([
        f"Текст-слой: {s['layer']} · размер {s['size']} · ширина {s['width'] if s['width'] is not None else 'auto'} · шрифт {s['font']}",
        f"Текст: заливка — {C.show_spec(s['text_fill'])}; контур — {C.show_spec(s['text_stroke'])}; толщина {s['stroke_w'] or 'как есть'}; циклов {s['cycles']}",
        f"Эмодзи: заливка — {C.show_spec(s['fill'])}; контур — {C.show_spec(s['stroke'])}; не красить: {', '.join(s['skip']) or '—'}",
        f"Удалять: {', '.join(s['remove']) or '—'}; авто logo/лого: {'вкл' if s['autologo'] else 'выкл'}",
        f"Лого: {'загружено' if ctx.user_data.get('logo') else 'нет'} · {s['logo_pos']} {s['logo_dx']}/{s['logo_dy']} · размер {s['logo_size']} · цвет {C.show_spec(s['logo_color'])}",
    ]))


async def reset(u, ctx):
    ctx.user_data["s"] = copy.deepcopy(P.DEFAULTS)
    ctx.user_data.pop("logo", None)
    await reply(u, "Настройки и лого сброшены (анимация осталась)")


def main():
    app = Application.builder().token(TOKEN).build()
    cmds = {
        "start": start, "help": start, "templates": tpl_list, "use": use, "go": go,
        "layer": set_layer, "font": set_font, "skip": set_skip, "remove": set_remove,
        "autologo": set_autologo, "logo": logo_cmd, "logopos": logopos, "tree": tree,
        "settings": settings, "reset": reset,
        "size": make_num_cmd("size", "Размер текста"),
        "width": make_num_cmd("width", "Макс. ширина (0 = без ограничения)", allow_auto=True),
        "strokew": make_num_cmd("stroke_w", "Толщина контура текста"),
        "cycles": make_num_cmd("cycles", "Циклов смены цвета за анимацию", cast=int),
        "logosize": make_num_cmd("logo_size", "Размер лого"),
        "textfill": make_spec_cmd("text_fill", "Заливка текста"),
        "textstroke": make_spec_cmd("text_stroke", "Контур текста"),
        "fill": make_spec_cmd("fill", "Заливка эмодзи", only_static=True),
        "stroke": make_spec_cmd("stroke", "Контур эмодзи", only_static=True),
        "logocolor": make_spec_cmd("logo_color", "Цвет лого", only_static=True),
    }
    for name, fn in cmds.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_tpl, pattern="^tpl:"))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.Sticker.ANIMATED, on_file))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
