"""تاتاروس - Telegram handlers and entry point. Run with: python main.py"""
import asyncio
import html
import logging
import re
import sys
import weakref
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent
from game import *  # noqa: F401,F403
from ui import *  # noqa: F401,F403

log = logging.getLogger("tatarus")


# ==========================================================================
# Story mode handlers (menus, battle, shop screens)
# ==========================================================================

story_router = Router(name="story")


class KeyedLock:
    def __init__(self) -> None:
        self._locks: "weakref.WeakValueDictionary[int, asyncio.Lock]" = weakref.WeakValueDictionary()

    def get(self, key: int) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock


LOCKS = KeyedLock()

# Taps that are waiting for (or holding) a user's lock; a burst of fast "hit" taps is
# resolved tap by tap but only the last one redraws the panel.
PENDING: dict[int, int] = {}
BURST: dict[int, dict] = {}


@dataclass
class Toast:
    text: str
    alert: bool = False


@dataclass
class Ctx:
    cq: types.CallbackQuery
    msg: types.Message
    uid: int
    args: list[str] = field(default_factory=list)


Route = Callable[[Ctx], Awaitable["Toast | None"]]
ROUTES: dict[str, Route] = {}


def route(name: str):
    def deco(fn: Route) -> Route:
        ROUTES[name] = fn
        return fn
    return deco


async def put(c: Ctx, scr: Screen) -> None:
    await show(c.msg, scr.keys, scr.text, scr.kb)


async def _register(user: types.User) -> tuple[bool]:
    _, created = await ensure_player(user.id, user.full_name, user.username)
    return (created,)


# ====================================================================== triggers
def _thread(m: types.Message) -> int | None:
    return m.message_thread_id if getattr(m, "is_topic_message", False) else None


@story_router.message(F.text.regexp(r"^\s*تاتاروس\s*$"))
@story_router.message(Command("menu", "tatarus"))
async def trigger_main(m: types.Message) -> None:
    if not m.from_user or m.from_user.is_bot:
        return
    await _register(m.from_user)
    scr = main_screen(m.from_user.id)
    await send_new(m.chat.id, scr.keys, scr.text, scr.kb, reply_to=m.message_id, thread_id=_thread(m))


@story_router.message(Command("story"))
async def trigger_story(m: types.Message) -> None:
    if not m.from_user or m.from_user.is_bot:
        return
    await _register(m.from_user)
    v = await get_view(m.from_user.id)
    ready = (await daily_status(m.from_user.id))["ready"]
    scr = game_menu_screen(m.from_user.id, v, ready)
    await send_new(m.chat.id, scr.keys, scr.text, scr.kb, reply_to=m.message_id, thread_id=_thread(m))


@story_router.message(F.text.regexp(r"^\s*(میدان نبرد|دمیج)\s*$"))
async def trigger_arena(m: types.Message) -> None:
    if not m.from_user or m.from_user.is_bot:
        return
    uid = m.from_user.id
    async with LOCKS.get(uid):
        await _register(m.from_user)
        v = await get_view(uid)
        if v and v.battle:
            out = await enter_battle(uid, v.battle.boss_id)
            scr = arena_screen(uid, out.view, enter_log(out.boss, False))
        else:
            scr = gates_screen(uid, v)
    await send_new(m.chat.id, scr.keys, scr.text, scr.kb, reply_to=m.message_id, thread_id=_thread(m))


# ====================================================================== callbacks
@story_router.callback_query(F.data.startswith("g:"))
async def on_callback(cq: types.CallbackQuery) -> None:
    parsed = parse_cb(cq.data)
    if parsed is None:
        await _safe_answer(cq)
        return
    action, args, owner = parsed
    if cq.from_user.id != owner:
        await _safe_answer(cq, "⛔️ این منو متعلق به شما نیست!", True)
        return
    msg = cq.message
    if not isinstance(msg, types.Message):
        await _safe_answer(cq, "این منو منقضی شده؛ دوباره «تاتاروس» را بنویس.", True)
        return
    handler = ROUTES.get(action)
    if handler is None:
        await _safe_answer(cq, "⏳ در حال توسعه...", True)
        return
    toast: Toast | None = None
    PENDING[owner] = PENDING.get(owner, 0) + 1
    try:
        async with LOCKS.get(owner):
            try:
                await _register(cq.from_user)
                toast = await handler(Ctx(cq, msg, owner, args))
            except Exception:
                log.exception("callback %s failed", cq.data)
                toast = Toast("خطای موقتی رخ داد؛ دوباره تلاش کن.", True)
    finally:
        PENDING[owner] -= 1
        if PENDING[owner] <= 0:
            PENDING.pop(owner, None)
    await _safe_answer(cq, toast.text if toast else None, toast.alert if toast else False)


async def _safe_answer(cq: types.CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    try:
        # Alerts cannot render custom emoji, so they carry plain text only.
        await cq.answer(strip_emoji(text) if text else None, show_alert=alert)
    except TelegramBadRequest as exc:
        log.debug("answer failed: %s", exc)


# ---------------------------------------------------------------- navigation
@route("close")
async def r_close(c: Ctx):
    await delete_message(c.msg.chat.id, c.msg.message_id)


@route("main")
async def r_main(c: Ctx):
    await put(c, main_screen(c.uid))


@route("story")
async def r_story(c: Ctx):
    await put(c, story_screen(c.uid))


@route("soon")
async def r_soon(c: Ctx):
    return Toast(SOON_TEXT, True)


@route("chars")
async def r_chars(c: Ctx):
    await put(c, chars_screen(c.uid, await get_view(c.uid)))


@route("pick")
async def r_pick(c: Ctx):
    cid = int(c.args[0]) if c.args and c.args[0].isdigit() else 0
    res = await select_character(c.uid, cid)
    if not res.ok:
        return Toast(res.msg, True)
    return await _game_menu(c)


async def _game_menu(c: Ctx):
    v = await get_view(c.uid)
    ready = (await daily_status(c.uid))["ready"]
    await put(c, game_menu_screen(c.uid, v, ready))


@route("menu")
async def r_menu(c: Ctx):
    return await _game_menu(c)


@route("gates")
async def r_gates(c: Ctx):
    await put(c, gates_screen(c.uid, await get_view(c.uid)))


@route("locked")
async def r_locked(c: Ctx):
    return Toast("🔒 اول باید دروازه‌ی قبلی را بگشایی و نگهبانش را بکشی!", True)


@route("boss")
async def r_boss(c: Ctx):
    boss = BOSSES.get(int(c.args[0])) if c.args and c.args[0].isdigit() else None
    if boss is None:
        return Toast("این دروازه وجود ندارد.", True)
    v = await get_view(c.uid)
    if boss.id > v.player.unlocked:
        return Toast("🔒 این دروازه هنوز بسته است!", True)
    await put(c, boss_screen(c.uid, v, boss))


# -------------------------------------------------------------------- battle
@route("fight")
async def r_fight(c: Ctx):
    boss_id = int(c.args[0]) if c.args and c.args[0].isdigit() else 0
    out = await enter_battle(c.uid, boss_id)
    if out.status == "error":
        return Toast(out.error, True)
    await put(c, arena_screen(c.uid, out.view, enter_log(out.boss, bool(out.amount))))
    return Toast("⚔️ وارد میدان شدی! حواست به جانت باشه...")


@route("cont")
async def r_cont(c: Ctx):
    v = await get_view(c.uid)
    if v.battle:
        out = await enter_battle(c.uid, v.battle.boss_id)
        await put(c, arena_screen(c.uid, out.view, enter_log(out.boss, False)))
        return None
    await put(c, gates_screen(c.uid, v))
    return Toast("نبرد فعالی نداری؛ یک دروازه انتخاب کن.")


@route("act")
async def r_act(c: Ctx):
    kind = c.args[0] if c.args else ""
    out = await act(c.uid, kind)
    queued = PENDING.get(c.uid, 0) > 1
    if out.status == "error":
        burst = None if queued else BURST.pop(c.uid, None)
        if burst and out.view is not None:
            await put(c, arena_screen(c.uid, out.view, burst_line(burst["hits"], burst["dmg"])))
        return Toast(out.error, True)
    if out.status in ("victory", "death"):
        BURST.pop(c.uid, None)
        if out.status == "victory":
            await put(c, victory_screen(c.uid, out))
            return Toast("پیروز شدی!")
        await put(c, defeat_screen(c.uid, out))
        return Toast("کشته شدی!")

    burst = BURST.setdefault(c.uid, {"hits": 0, "dmg": 0})
    if kind in ("hit", "power", "pet"):
        burst["hits"] += 1
        burst["dmg"] += out.dmg
    if queued:
        return None
    BURST.pop(c.uid, None)
    line = battle_log(out)
    if burst["hits"] > 1:
        line = burst_line(burst["hits"], burst["dmg"]) + "\n" + line
    await put(c, arena_screen(c.uid, out.view, line))
    return None


# ------------------------------------------------------------------- weapons
@route("upg")
async def r_upg(c: Ctx):
    await put(c, upgrade_screen(c.uid, await get_view(c.uid)))


def _weapon_key(c: Ctx) -> str | None:
    key = c.args[0] if c.args else ""
    return key if key in WEAPONS else None


@route("wpn")
async def r_wpn(c: Ctx):
    key = _weapon_key(c)
    if key is None:
        return Toast("سلاح نامعتبر است.", True)
    await put(c, weapon_screen(c.uid, await get_view(c.uid), key))


async def _weapon_action(c: Ctx, fn):
    key = _weapon_key(c)
    if key is None:
        return Toast("سلاح نامعتبر است.", True)
    res = await fn(c.uid, key)
    await put(c, weapon_screen(c.uid, await get_view(c.uid), key))
    return Toast(("✅ " if res.ok else "⚠️ ") + res.msg, True)


@route("wbuy")
async def r_wbuy(c: Ctx):
    return await _weapon_action(c, buy_weapon)


@route("wup")
async def r_wup(c: Ctx):
    return await _weapon_action(c, upgrade_weapon)


@route("wequip")
async def r_wequip(c: Ctx):
    return await _weapon_action(c, equip_weapon)


# ----------------------------------------------------------- daily / tasks / pets
@route("daily")
async def r_daily(c: Ctx):
    await put(c, daily_screen(c.uid, await daily_status(c.uid)))


@route("claimd")
async def r_claimd(c: Ctx):
    res = await claim_daily(c.uid)
    status = await daily_status(c.uid)
    if not res.ok:
        await put(c, daily_screen(c.uid, status))
        return Toast(res.msg, True)
    await put(c, daily_screen(c.uid, status, res.data))
    return Toast("🎉 جوایز روزانه با موفقیت به حساب شما اضافه شد!", True)


async def _tasks(c: Ctx):
    v = await get_view(c.uid)
    await put(c, tasks_screen(c.uid, v, await get_tasks(c.uid)))


@route("tasks")
async def r_tasks(c: Ctx):
    return await _tasks(c)


@route("claimt")
async def r_claimt(c: Ctx):
    res = await claim_task(c.uid, c.args[0] if c.args else "")
    await _tasks(c)
    if not res.ok:
        return Toast(res.msg, True)
    d = res.data
    extra = f" + {d['gold']} طلا" if d["gold"] else ""
    return Toast(f"🎁 {d['coins']:,} سکه + {d['xp']} XP{extra} گرفتی!", True)


@route("pets")
async def r_pets(c: Ctx):
    await put(c, pets_screen(c.uid, await get_view(c.uid)))


@route("petog")
async def r_petog(c: Ctx):
    cid = int(c.args[0]) if c.args and c.args[0].isdigit() else 0
    res = await toggle_pet(c.uid, cid)
    await put(c, pets_screen(c.uid, await get_view(c.uid)))
    return Toast(("⚔️ " if res.ok else "⚠️ ") + res.msg, True)


# ---------------------------------------------------------------- misc screens
@route("guide")
async def r_guide(c: Ctx):
    page = int(c.args[0]) if c.args and c.args[0].isdigit() else 1
    await put(c, guide_screen(c.uid, page))


@route("profile")
async def r_profile(c: Ctx):
    v = await get_view(c.uid)
    await put(c, profile_screen(c.uid, v, await rank_of(c.uid)))


@route("top")
async def r_top(c: Ctx):
    await put(c, leaderboard_screen(c.uid, await leaderboard(10), await rank_of(c.uid)))


# ==========================================================================
# /start, referral and pet purchase
# ==========================================================================

shop_router = Router(name="shop")

CANCEL_WORDS = {"انصراف", "لغو", "/cancel"}


class UserBuy(StatesGroup):
    waiting_for_contact = State()
    waiting_for_receipt = State()


async def notify(user_id: int, text: str) -> None:
    await tg.call("sendMessage", {"chat_id": user_id, "text": text, "parse_mode": "HTML"})


# ====================================================================== /start
@shop_router.message(CommandStart())
async def cmd_start(m: types.Message, command: CommandObject, state: FSMContext) -> None:
    if not m.from_user or m.from_user.is_bot:
        return
    await state.clear()
    user = m.from_user
    _, created = await ensure_player(user.id, user.full_name, user.username)
    arg = (command.args or "").strip()

    if arg.startswith("buypet_"):
        await begin_pet_purchase(m, state, arg.split("_", 1)[1])
        return

    welcome = ""
    if arg.startswith("ref_") and created and arg[4:].isdigit():
        inviter = int(arg[4:])
        if await apply_referral(user.id, inviter):
            welcome = (f"{ic('gift')} با دعوت دوستت وارد شدی و <b>{REFERRAL_INVITEE_COINS:,}</b> سکه هدیه گرفتی!\n\n")
            await notify(
                inviter,
                f"{ic('gift')} <b>{html.escape(user.full_name)}</b> با لینک تو وارد تاتاروس شد!\n"
                f"{ic('coin')} <b>+{REFERRAL_INVITER_COINS:,}</b> سکه و <b>+{REFERRAL_INVITER_XP}</b> XP گرفتی.",
            )
    if created and not welcome:
        welcome = f"{e('5296480809602023717', '👋')} <b>به دنیای تاتاروس خوش آمدی!</b>\n\n"

    scr = main_screen(user.id)
    tip = ""
    if m.chat.type == "private":
        tip = "\n\n<i>می‌توانی ربات را به گروهت اضافه کنی و بنویسی «تاتاروس»؛ یا همین‌جا بازی کنی.</i>"
    await send_new(m.chat.id, scr.keys, welcome + scr.text + tip, scr.kb, reply_to=m.message_id)


@shop_router.message(Command("cancel"))
async def cmd_cancel(m: types.Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        return
    await state.clear()
    await m.answer("✅ لغو شد.", reply_markup=types.ReplyKeyboardRemove())


# ============================================================ pet purchase flow
async def begin_pet_purchase(m: types.Message, state: FSMContext, raw_char: str) -> None:
    if not raw_char.isdigit() or int(raw_char) not in CHARACTERS:
        await m.reply("❌ لینک خرید نامعتبر است.")
        return
    char_id = int(raw_char)
    reason = await pet_order_blocker(m.from_user.id, char_id)
    if reason:
        await m.reply(f"⚠️ {reason}")
        return
    await state.set_state(UserBuy.waiting_for_contact)
    await state.update_data(buy_char_id=char_id)
    kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="ارسال شماره تلفن 📱", request_contact=True)], [types.KeyboardButton(text="انصراف")]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    ch = CHARACTERS[char_id]
    await m.reply(f"🐾 خرید حیوان نبرد «{ch.pet_name}»\n\nشماره تلفن خودت را با دکمه‌ی زیر تایید کن:", reply_markup=kb)


@shop_router.message(F.text.in_(CANCEL_WORDS), UserBuy.waiting_for_contact)
@shop_router.message(F.text.in_(CANCEL_WORDS), UserBuy.waiting_for_receipt)
async def cancel_purchase(m: types.Message, state: FSMContext) -> None:
    await state.clear()
    await m.reply("✅ خرید لغو شد.", reply_markup=types.ReplyKeyboardRemove())


@shop_router.message(F.contact, UserBuy.waiting_for_contact)
async def receive_contact(m: types.Message, state: FSMContext) -> None:
    if m.contact.user_id != m.from_user.id:
        await m.reply("❌ فقط شماره‌ی خودت را می‌توانی بفرستی. با دکمه‌ی «ارسال شماره تلفن» تایید کن.")
        return
    data = await state.get_data()
    char_id = int(data.get("buy_char_id", 0))
    await state.update_data(phone=m.contact.phone_number)
    await m.reply("✅ شماره دریافت شد.", reply_markup=types.ReplyKeyboardRemove())
    card = get_setting("text_bank_card_text") or get_setting("bank_card_text") or "شماره کارت هنوز توسط ادمین تنظیم نشده است."
    kb = [[btn("واریز کردم", f"paid:{char_id}"), btn("انصراف", "paid_cancel")]]
    await tg.call("sendMessage", {
        "chat_id": m.chat.id, "text": parse_emojis(card), "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": kb},
    })


@shop_router.message(UserBuy.waiting_for_contact)
async def contact_expected(m: types.Message) -> None:
    await m.reply("برای ادامه، دکمه‌ی «ارسال شماره تلفن 📱» را بزن یا «انصراف» را بفرست.")


@shop_router.callback_query(F.data == "paid_cancel")
async def paid_cancel(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer("لغو شد.")
    if isinstance(cq.message, types.Message):
        await tg.call("deleteMessage", {"chat_id": cq.message.chat.id, "message_id": cq.message.message_id})


@shop_router.callback_query(F.data.startswith("paid:"))
async def paid_callback(cq: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if cq.data.split(":", 1)[1] != str(data.get("buy_char_id")) or "phone" not in data:
        await cq.answer("این درخواست منقضی شده؛ دوباره از داخل بازی «خریدن حیوان» را بزن.", show_alert=True)
        return
    await state.set_state(UserBuy.waiting_for_receipt)
    await cq.answer()
    if isinstance(cq.message, types.Message):
        await tg.call("editMessageReplyMarkup", {"chat_id": cq.message.chat.id, "message_id": cq.message.message_id, "reply_markup": {"inline_keyboard": []}})
        await cq.message.answer("📸 عکس رسید واریزی را ارسال کن (یا «انصراف» بفرست):")


@shop_router.message(F.photo, UserBuy.waiting_for_receipt)
async def receive_receipt(m: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    char_id = int(data.get("buy_char_id", 0))
    phone = data.get("phone", "نامشخص")
    res = await create_pet_order(m.from_user.id, char_id, phone)
    if not res.ok:
        await state.clear()
        await m.reply(f"⚠️ {res.msg}")
        return
    oid = res.data["order_id"]
    ch = CHARACTERS[char_id]
    user = m.from_user
    caption = (
        f"💰 <b>درخواست خرید حیوان نبرد</b> (#{oid})\n"
        f"🐾 {html.escape(ch.pet_name)} — کاراکتر {char_id}\n\n"
        f"👤 کاربر: {html.escape(user.full_name)}\n"
        f"🆔 آیدی: <code>{user.id}</code>\n"
        f"🌐 یوزرنیم: @{user.username or 'ندارد'}\n"
        f"📱 شماره: <code>{html.escape(str(phone))}</code>\n\n"
        "آیا این واریزی تایید است؟"
    )
    kb = [[{"text": "تایید", "callback_data": f"pet_ok:{oid}", "style": "success", "icon_custom_emoji_id": ICONS["ok"][0]},
           {"text": "رد", "callback_data": f"pet_no:{oid}", "style": "danger", "icon_custom_emoji_id": ICONS["cross"][0]}]]
    delivered = False
    for admin in ADMIN_IDS:
        r = await tg.call("sendPhoto", {
            "chat_id": admin, "photo": m.photo[-1].file_id, "caption": caption,
            "parse_mode": "HTML", "reply_markup": {"inline_keyboard": kb},
        })
        delivered = delivered or ok(r)
    await state.clear()
    if delivered:
        await m.reply("✅ رسید تو برای ادمین ارسال شد. پس از تایید، حیوانت فعال می‌شود و به تو خبر می‌دهم.")
    else:
        await decide_pet_order(oid, 0, approve=False)
        await m.reply("⚠️ ارسال رسید به ادمین ممکن نشد. کمی بعد دوباره تلاش کن.")


@shop_router.message(UserBuy.waiting_for_receipt)
async def receipt_expected(m: types.Message) -> None:
    await m.reply("فقط «عکس» رسید را بفرست یا «انصراف» را بزن.")


@shop_router.callback_query(F.data.startswith("pet_ok:") | F.data.startswith("pet_no:"))
async def pet_decision(cq: types.CallbackQuery) -> None:
    if cq.from_user.id not in ADMIN_IDS:
        await cq.answer("⛔️ فقط ادمین", show_alert=True)
        return
    action, _, raw = cq.data.partition(":")
    if not raw.isdigit():
        await cq.answer()
        return
    approve = action == "pet_ok"
    res = await decide_pet_order(int(raw), cq.from_user.id, approve)
    if not res.ok:
        await cq.answer(res.msg, show_alert=True)
        if isinstance(cq.message, types.Message):
            await tg.call("editMessageReplyMarkup", {"chat_id": cq.message.chat.id, "message_id": cq.message.message_id, "reply_markup": {"inline_keyboard": []}})
        return
    uid, char_id = res.data["user_id"], res.data["char_id"]
    if isinstance(cq.message, types.Message):
        base = cq.message.caption or ""
        await tg.call("editMessageCaption", {
            "chat_id": cq.message.chat.id, "message_id": cq.message.message_id,
            "caption": html.escape(base) + (f"\n\n{ic('ok')} <b>تایید شد.</b>" if approve else f"\n\n{ic('cross')} <b>رد شد.</b>"),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": []},
        })
    if approve:
        pet = CHARACTERS[char_id]
        await notify(uid, f"{e('6041909294771739947', '🔥')} <b>حیوان نبردت فعال شد!</b>\n"
                          f"{e(*pet.pet_icon)} <b>{html.escape(pet.pet_name)}</b> از حالا در میدان کنار توست. مبارک باشه رفیق!")
    else:
        await notify(uid, "❌ متاسفانه رسید شما تایید نشد. اگر اشتباهی رخ داده با ادمین در ارتباط باش.")
    await cq.answer("انجام شد.")


# ==========================================================================
# Admin panel («تغییرات»)
# ==========================================================================

admin_router = Router(name="admin")
admin_router.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin_router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


class AdminSetup(StatesGroup):
    waiting_for_media = State()
    waiting_for_text = State()
    waiting_for_emoji_btn = State()
    waiting_for_emoji_code = State()
    guide_text_page = State()
    guide_photo_page = State()
    waiting_for_char_names = State()
    grant_user = State()
    grant_amount = State()


MEDIA_TARGETS = {
    "main": "منوی اصلی", "story": "اوپنینگ داستانی", "character": "انتخاب کاراکتر", "gamemenu": "منوی داستانی",
    "gamestart": "دروازه‌ها", "battle": "میدان نبرد", "victory": "پیروزی", "defeat": "شکست",
    "upgrade": "منوی ارتقا", "gamedaily": "جایزه روزانه", "tasks": "تسک‌ها", "profile": "پروفایل", "leaderboard": "لیدربرد",
}
for _bid, _boss in BOSSES.items():
    MEDIA_TARGETS[f"boss_{_bid}"] = f"باس {_bid}: {_boss.name}"
for _cid, _ch in CHARACTERS.items():
    MEDIA_TARGETS[f"pet_{_cid}"] = f"حیوان کاراکتر {_cid}: {_ch.pet_name}"
for _wk, _w in WEAPONS.items():
    MEDIA_TARGETS[f"weapon_{_wk}"] = f"سلاح {_w.name}"

TEXT_KEYS = {
    "main_menu": "متن منوی اصلی",
    "story_intro": "متن اوپنینگ داستانی",
    "char_select": "سربرگ انتخاب کاراکتر",
    "game_menu": "سربرگ منوی داستانی",
    "upgrade_intro": "سربرگ کارگاه سلاح",
    "pet_text": "متن حیوانات (جایگزین توضیح پیش‌فرض)",
    "bank_card_text": "شماره کارت / متن پرداخت",
}


def kb(*rows: list[tuple[str, str]]) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )


def mark(key: str) -> str:
    return "✅" if get_setting(key) else "❌"


def cancel_kb() -> types.InlineKeyboardMarkup:
    return kb([("🔙 بازگشت (لغو)", "adm_cancel")])


def home_kb():
    return kb([("منو اصلی", "adm_cat_main"), ("داستانی", "adm_cat_story")], [("👥 بازیکنان", "adm_cat_players")])


def players_kb():
    return kb([("📊 آمار", "adm_stats")], [("🎁 هدیه/تغییر بازیکن", "adm_grant")], [("بازگشت", "adm_home")])


def story_kb():
    return kb(
        [("🎬 رسانه‌ها", "adm_cat_media"), ("👹 باس‌ها", "adm_cat_bosses")],
        [("🐾 حیوانات", "adm_cats_pets"), ("⚔️ سلاح‌ها", "adm_cats_weapons")],
        [("📝 متن‌ها", "adm_cat_texts"), ("اسم کاراکترها", "adm_charnames")],
        [("📖 راهنما (متن)", "adm_guidetext"), ("📸 راهنما (عکس)", "adm_guidephoto")],
        [("♻️ ریست راهنما", "adm_guidereset"), ("✨ ایموجی دکمه‌ها", "adm_emoji")],
        [("بازگشت", "adm_home")],
    )


def grid(items: list[tuple[str, str]], per_row: int = 2, back: str = "adm_cat_story"):
    rows = [items[i:i + per_row] for i in range(0, len(items), per_row)]
    rows.append([("بازگشت", back)])
    return kb(*rows)


async def edit(cq: types.CallbackQuery, text: str, markup: types.InlineKeyboardMarkup) -> None:
    try:
        await cq.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc):
            await cq.message.answer(text, reply_markup=markup)


# ====================================================================== navigation
@admin_router.message(F.text == "تغییرات")
async def open_panel(m: types.Message, state: FSMContext) -> None:
    await state.clear()
    if not ADMIN_IDS:
        return
    await m.reply("⚙️ پنل مدیریت تاتاروس\n\nبخش مورد نظر را انتخاب کنید:", reply_markup=home_kb())


@admin_router.callback_query(F.data == "adm_home")
async def nav_home(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit(cq, "⚙️ پنل مدیریت تاتاروس\n\nبخش مورد نظر را انتخاب کنید:", home_kb())
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cat_main")
async def nav_main(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    markup = kb(
        [(f"عکس منو {mark('photo_main')}", "adm_media:main")],
        [("📝 متن منوی اصلی", "adm_text:main_menu")],
        [("بازگشت", "adm_home")],
    )
    await edit(cq, "⚙️ تنظیمات منوی اصلی:", markup)
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cat_story")
async def nav_story(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit(cq, "⚙️ تنظیمات بخش داستانی:", story_kb())
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cat_players")
async def nav_players(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit(cq, "👥 مدیریت بازیکنان:", players_kb())
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cat_media")
async def nav_media(cq: types.CallbackQuery) -> None:
    keys = ["story", "character", "gamemenu", "gamestart", "battle", "victory", "defeat", "upgrade", "gamedaily", "tasks", "profile", "leaderboard"]
    await edit(cq, "🎬 رسانه‌ی کدام بخش را می‌خواهید تنظیم کنید؟", grid([(f"{MEDIA_TARGETS[k]} {mark('photo_' + k)}", f"adm_media:{k}") for k in keys]))
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cat_bosses")
async def nav_bosses(cq: types.CallbackQuery) -> None:
    items = [(f"{b.name} {mark(f'photo_boss_{i}')}", f"adm_media:boss_{i}") for i, b in BOSSES.items()]
    await edit(cq, "👹 رسانه‌ی معرفی کدام باس؟ (در میدان نبرد از رسانه‌ی «میدان نبرد» استفاده می‌شود)", grid(items))
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cats_pets")
async def nav_pets(cq: types.CallbackQuery) -> None:
    items = [(f"{c.pet_name} {mark(f'photo_pet_{i}')}", f"adm_media:pet_{i}") for i, c in CHARACTERS.items()]
    await edit(cq, "حیوان کدام کاراکتر را می‌خواهید تنظیم کنید؟", grid(items))
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cats_weapons")
async def nav_weapons(cq: types.CallbackQuery) -> None:
    items = [(f"{w.name} {mark(f'photo_weapon_{k}')}", f"adm_media:weapon_{k}") for k, w in WEAPONS.items()]
    await edit(cq, "عکس کدام سلاح را می‌خواهید تنظیم کنید؟", grid(items))
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cat_texts")
async def nav_texts(cq: types.CallbackQuery) -> None:
    items = [(f"{label} {'✏️' if get_setting('text_' + key) or (key in ('pet_text', 'bank_card_text') and get_setting(key)) else '·'}", f"adm_text:{key}")
             for key, label in TEXT_KEYS.items()]
    await edit(cq, "📝 کدام متن را می‌خواهید تغییر دهید؟ (✏️ یعنی سفارشی شده)", grid(items, per_row=1))
    await cq.answer()


@admin_router.callback_query(F.data == "adm_cancel")
async def cancel(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit(cq, "❌ عملیات لغو شد.\n\n⚙️ پنل مدیریت تاتاروس:", home_kb())
    await cq.answer()


# ====================================================================== media
@admin_router.callback_query(F.data.startswith("adm_media:"))
async def ask_media(cq: types.CallbackQuery, state: FSMContext) -> None:
    target = cq.data.split(":", 1)[1]
    if target not in MEDIA_TARGETS:
        await cq.answer("نامعتبر", show_alert=True)
        return
    await state.set_state(AdminSetup.waiting_for_media)
    await state.update_data(target=target)
    rows = [[("🗑 حذف رسانه‌ی فعلی", f"adm_mediadel:{target}")], [("🔙 بازگشت (لغو)", "adm_cancel")]]
    await edit(cq, f"🎥 عکس، ویدیو یا گیف «{MEDIA_TARGETS[target]}» را ارسال کنید:", kb(*rows))
    await cq.answer()


@admin_router.callback_query(F.data.startswith("adm_mediadel:"))
async def delete_media(cq: types.CallbackQuery, state: FSMContext) -> None:
    target = cq.data.split(":", 1)[1]
    await db.delete(f"photo_{target}", f"type_{target}", f"uniq_{target}")
    await state.clear()
    await edit(cq, f"🗑 رسانه‌ی «{MEDIA_TARGETS.get(target, target)}» حذف شد.\n\nپنل مدیریت:", home_kb())
    await cq.answer()


@admin_router.message(F.photo | F.video | F.animation, AdminSetup.waiting_for_media)
async def receive_media(m: types.Message, state: FSMContext) -> None:
    if m.animation:
        media, kind = m.animation, "animation"
    elif m.video:
        media, kind = m.video, "video"
    else:
        media, kind = m.photo[-1], "photo"
    await state.update_data(file_id=media.file_id, uniq=media.file_unique_id, kind=kind)
    await m.reply("آیا این فایل رسانه‌ای تایید است؟", reply_markup=kb([("✅ بله", "adm_ok_media"), ("❌ لغو", "adm_cancel")]))


@admin_router.message(AdminSetup.waiting_for_media)
async def media_expected(m: types.Message) -> None:
    await m.reply("❌ لطفا فقط عکس، ویدیو یا گیف ارسال کنید.")


@admin_router.callback_query(F.data == "adm_ok_media", AdminSetup.waiting_for_media)
async def confirm_media(cq: types.CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if "file_id" not in d:
        await cq.answer("اول فایل را بفرستید.", show_alert=True)
        return
    t = d["target"]
    await set_setting(f"photo_{t}", d["file_id"])
    await set_setting(f"type_{t}", d["kind"])
    await set_setting(f"uniq_{t}", d["uniq"])
    await state.clear()
    await edit(cq, f"✅ رسانه‌ی «{MEDIA_TARGETS[t]}» ذخیره شد!\n\nپنل مدیریت:", home_kb())
    await cq.answer()


# ====================================================================== texts
@admin_router.callback_query(F.data.startswith("adm_text:"))
async def ask_text(cq: types.CallbackQuery, state: FSMContext) -> None:
    key = cq.data.split(":", 1)[1]
    if key not in TEXT_KEYS:
        await cq.answer("نامعتبر", show_alert=True)
        return
    await state.set_state(AdminSetup.waiting_for_text)
    await state.update_data(key=key)
    note = ("\n\nنکته: می‌توانید از HTML (مثل <b>متن</b>) و کد عددی ایموجی پریمیوم (۱۸ تا ۲۲ رقم) داخل متن استفاده کنید."
            "\nدر هر لحظه «♻️ بازگشت به پیش‌فرض» متن اصلی ربات را برمی‌گرداند.")
    rows = [[("♻️ بازگشت به پیش‌فرض", f"adm_textdel:{key}")], [("🔙 بازگشت (لغو)", "adm_cancel")]]
    await edit(cq, f"📝 متن جدید برای «{TEXT_KEYS[key]}» را ارسال کنید:{note}", kb(*rows))
    await cq.answer()


@admin_router.callback_query(F.data.startswith("adm_textdel:"))
async def reset_text(cq: types.CallbackQuery, state: FSMContext) -> None:
    key = cq.data.split(":", 1)[1]
    await db.delete(f"text_{key}", *([key] if key in ("pet_text", "bank_card_text") else []))
    await state.clear()
    await edit(cq, f"♻️ «{TEXT_KEYS.get(key, key)}» به پیش‌فرض برگشت.\n\nپنل مدیریت:", home_kb())
    await cq.answer()


@admin_router.message(F.text, AdminSetup.waiting_for_text)
async def receive_text(m: types.Message, state: FSMContext) -> None:
    probe = await tg.call("sendMessage", {
        "chat_id": m.chat.id, "text": parse_emojis(m.text), "parse_mode": "HTML",
    })
    if not ok(probe):
        await m.reply(f"❌ این متن در تلگرام معتبر نیست (HTML ناقص؟):\n{probe.get('description')}\n\nدوباره بفرستید.")
        return
    await state.update_data(text=m.text)
    await m.reply("☝️ پیش‌نمایش بالا همان چیزی است که کاربران می‌بینند. تایید می‌کنید؟",
                  reply_markup=kb([("✅ بله", "adm_ok_text"), ("❌ لغو", "adm_cancel")]))


@admin_router.message(AdminSetup.waiting_for_text)
async def text_expected(m: types.Message) -> None:
    await m.reply("❌ فقط متن بفرستید.")


@admin_router.callback_query(F.data == "adm_ok_text", AdminSetup.waiting_for_text)
async def confirm_text(cq: types.CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if "text" not in d:
        await cq.answer("اول متن را بفرستید.", show_alert=True)
        return
    await set_setting(f"text_{d['key']}", d["text"])
    await state.clear()
    await edit(cq, "✅ متن با موفقیت تنظیم شد!\n\nپنل مدیریت:", home_kb())
    await cq.answer()


# ====================================================================== emoji of buttons
@admin_router.callback_query(F.data == "adm_emoji")
async def ask_emoji_button(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSetup.waiting_for_emoji_btn)
    names = "\n".join(f"• {n}" for n in button_names())
    await edit(cq, f"نام دقیق دکمه‌ای که می‌خواهید ایموجی‌اش عوض شود را بفرستید (مثال: شروع):\n\n{names}", cancel_kb())
    await cq.answer()


@admin_router.message(F.text, AdminSetup.waiting_for_emoji_btn)
async def receive_emoji_button(m: types.Message, state: FSMContext) -> None:
    name = m.text.strip()
    if name not in button_names():
        await m.reply("❌ چنین دکمه‌ای وجود ندارد. دقیقاً یکی از نام‌های لیست را بفرستید.", reply_markup=cancel_kb())
        return
    await state.update_data(btn=name)
    await state.set_state(AdminSetup.waiting_for_emoji_code)
    await m.reply(f"کد ایموجی پریمیوم جدید برای «{name}» را بفرستید (فقط عدد). برای برگشت به پیش‌فرض بنویسید: حذف", reply_markup=cancel_kb())


@admin_router.message(F.text, AdminSetup.waiting_for_emoji_code)
async def receive_emoji_code(m: types.Message, state: FSMContext) -> None:
    d = await state.get_data()
    code = m.text.strip()
    if code == "حذف":
        await db.delete(f"emoji_{d['btn']}")
        done = f"♻️ ایموجی دکمه‌ی «{d['btn']}» به پیش‌فرض برگشت."
    elif code.isdigit() and 15 <= len(code) <= 22:
        await set_setting(f"emoji_{d['btn']}", code)
        done = f"✅ ایموجی دکمه‌ی «{d['btn']}» تغییر یافت."
    else:
        await m.reply("❌ کد باید فقط عدد (۱۵ تا ۲۲ رقم) باشد.", reply_markup=cancel_kb())
        return
    await state.clear()
    await m.reply(f"{done}\n\nپنل مدیریت:", reply_markup=story_kb())


# ====================================================================== character names
@admin_router.callback_query(F.data == "adm_charnames")
async def ask_char_names(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSetup.waiting_for_char_names)
    await state.update_data(char=1)
    await edit(cq, "تغییر اسم کاراکترها:\n📝 اسم + (اختیاری) کد ایموجی پریمیوم کاراکتر ۱ را بفرستید (مثال: زولو 5832457500821034730):", cancel_kb())
    await cq.answer()


@admin_router.message(F.text, AdminSetup.waiting_for_char_names)
async def receive_char_name(m: types.Message, state: FSMContext) -> None:
    raw = m.text.strip()
    match = re.search(r"(\d{15,22})", raw)
    emoji_id = match.group(1) if match else ""
    name = raw.replace(emoji_id, "").strip() if emoji_id else raw
    if not name:
        await m.reply("❌ اسم خالی است.", reply_markup=cancel_kb())
        return
    await state.update_data(name=name, emoji=emoji_id)
    await m.reply(f"آیا این اسم تایید است؟\n\nنام: {name}\nایموجی: {emoji_id or 'پیش‌فرض'}",
                  reply_markup=kb([("✅ بله", "adm_ok_char"), ("❌ لغو", "adm_cancel")]))


@admin_router.message(AdminSetup.waiting_for_char_names)
async def char_name_expected(m: types.Message) -> None:
    await m.reply("❌ فقط متن بفرستید.")


@admin_router.callback_query(F.data == "adm_ok_char", AdminSetup.waiting_for_char_names)
async def confirm_char_name(cq: types.CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    cid = int(d.get("char", 1))
    if "name" not in d:
        await cq.answer("اول اسم را بفرستید.", show_alert=True)
        return
    await set_setting(f"char{cid}_name", d["name"])
    if d.get("emoji"):
        await set_setting(f"char{cid}_emoji", d["emoji"])
    else:
        await db.delete(f"char{cid}_emoji")
    if cid >= len(CHARACTERS):
        await state.clear()
        await edit(cq, "🎉 تنظیمات اسم هر ۴ کاراکتر به پایان رسید.\n\nپنل مدیریت:", story_kb())
    else:
        await state.set_data({"char": cid + 1})
        await edit(cq, f"✅ کاراکتر {cid} ذخیره شد.\n\nاسم کاراکتر {cid + 1} را بفرستید:", cancel_kb())
    await cq.answer()


# ====================================================================== guide
@admin_router.callback_query(F.data == "adm_guidetext")
async def ask_guide_text(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSetup.guide_text_page)
    await state.update_data(page=1, saved=0)
    await edit(cq, "📖 راهنمای جدید (جایگزین راهنمای فعلی می‌شود)\n\nمتن صفحه ۱ را بفرستید:", cancel_kb())
    await cq.answer()


@admin_router.message(F.text, AdminSetup.guide_text_page)
async def receive_guide_text(m: types.Message, state: FSMContext) -> None:
    probe = await tg.call("sendMessage", {
        "chat_id": m.chat.id, "text": parse_emojis(m.text), "parse_mode": "HTML",
    })
    if not ok(probe):
        await m.reply(f"❌ متن معتبر نیست:\n{probe.get('description')}")
        return
    await state.update_data(text=m.text)
    await m.reply("☝️ پیش‌نمایش بالا. تایید می‌کنید؟",
                  reply_markup=kb([("✅ بله", "adm_ok_gtext"), ("❌ لغو", "adm_cancel")]))


@admin_router.message(AdminSetup.guide_text_page)
async def guide_text_expected(m: types.Message) -> None:
    await m.reply("❌ فقط متن بفرستید.")


@admin_router.callback_query(F.data == "adm_ok_gtext", AdminSetup.guide_text_page)
async def confirm_guide_text(cq: types.CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if "text" not in d:
        await cq.answer("اول متن را بفرستید.", show_alert=True)
        return
    page = int(d.get("page", 1))
    await set_setting(f"guide_text_{page}", d["text"])
    await set_setting("guide_pages_count", str(page))
    await state.update_data(saved=page, text=None)
    await edit(cq, "صفحه بعد را هم اضافه می‌کنید؟", kb([("✅ بله", "adm_gnext"), ("❌ خیر و اتمام", "adm_gdone")]))
    await cq.answer()


@admin_router.callback_query(F.data == "adm_gnext", AdminSetup.guide_text_page)
async def guide_next(cq: types.CallbackQuery, state: FSMContext) -> None:
    page = int((await state.get_data()).get("page", 1)) + 1
    await state.update_data(page=page, text=None)
    await edit(cq, f"متن صفحه {page} را بفرستید:", cancel_kb())
    await cq.answer()


@admin_router.callback_query(F.data == "adm_gdone", AdminSetup.guide_text_page)
async def guide_done(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit(cq, "✅ ثبت راهنمای متنی به پایان رسید.\n\nپنل مدیریت:", story_kb())
    await cq.answer()


@admin_router.callback_query(F.data == "adm_guidephoto")
async def ask_guide_photo(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSetup.guide_photo_page)
    await state.update_data(page=1, total=guide_page_count())
    await edit(cq, f"📸 عکس راهنما (صفحه 1 از {guide_page_count()}) را ارسال کنید:", cancel_kb())
    await cq.answer()


@admin_router.message(F.photo, AdminSetup.guide_photo_page)
async def receive_guide_photo(m: types.Message, state: FSMContext) -> None:
    await state.update_data(file_id=m.photo[-1].file_id, uniq=m.photo[-1].file_unique_id)
    await m.reply("آیا این عکس تایید است؟", reply_markup=kb([("✅ بله", "adm_ok_gphoto"), ("❌ لغو", "adm_cancel")]))


@admin_router.message(AdminSetup.guide_photo_page)
async def guide_photo_expected(m: types.Message) -> None:
    await m.reply("❌ فقط عکس بفرستید.")


@admin_router.callback_query(F.data == "adm_ok_gphoto", AdminSetup.guide_photo_page)
async def confirm_guide_photo(cq: types.CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    if "file_id" not in d:
        await cq.answer("اول عکس را بفرستید.", show_alert=True)
        return
    page, total = int(d["page"]), int(d["total"])
    await set_setting(f"photo_guide_{page}", d["file_id"])
    await set_setting(f"type_guide_{page}", "photo")
    await set_setting(f"uniq_guide_{page}", d["uniq"])
    if page < total:
        await state.update_data(page=page + 1, file_id=None)
        await edit(cq, f"✅ عکس صفحه {page} ذخیره شد.\n📸 عکس صفحه {page + 1} را ارسال کنید:", cancel_kb())
    else:
        await state.clear()
        await edit(cq, "✅ عکس تمامی صفحات راهنما ذخیره شد.\n\nپنل مدیریت:", story_kb())
    await cq.answer()


@admin_router.callback_query(F.data == "adm_guidereset")
async def reset_guide(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await db.delete_prefix("guide_text_")
    await db.delete_prefix("photo_guide_")
    await db.delete_prefix("type_guide_")
    await db.delete_prefix("uniq_guide_")
    await db.delete("guide_pages_count")
    await edit(cq, "♻️ راهنما به حالت پیش‌فرض برگشت.\n\nپنل مدیریت:", story_kb())
    await cq.answer()


# ====================================================================== players
@admin_router.callback_query(F.data == "adm_stats")
async def show_stats(cq: types.CallbackQuery) -> None:
    s = await admin_stats()
    text = (
        "📊 آمار تاتاروس\n\n"
        f"👥 بازیکنان: {s['players']:,}\n🟢 فعال (۲۴ ساعت): {s['active']:,}\n⚔️ در نبرد همین حالا: {s['fighting']:,}\n"
        f"👹 مجموع باس‌کشی: {s['kills']:,}\n💀 مجموع مرگ‌ها: {s['deaths']:,}\n🐾 حیوانات فعال: {s['pets']:,}\n"
        f"🪙 مجموع سکه‌ی بازیکنان: {s['coins']:,}"
    )
    await edit(cq, text, kb([("🔄 تازه‌سازی", "adm_stats")], [("بازگشت", "adm_cat_players")]))
    await cq.answer()


@admin_router.callback_query(F.data == "adm_grant")
async def ask_grant_user(cq: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSetup.grant_user)
    await edit(cq, "آیدی عددی بازیکن را بفرستید (او باید قبلاً بازی را شروع کرده باشد):", cancel_kb())
    await cq.answer()


@admin_router.message(F.text, AdminSetup.grant_user)
async def receive_grant_user(m: types.Message, state: FSMContext) -> None:
    raw = m.text.strip()
    if not raw.isdigit():
        await m.reply("❌ فقط آیدی عددی.", reply_markup=cancel_kb())
        return
    view = await get_view(int(raw))
    if view is None:
        await m.reply("❌ این کاربر هنوز بازی را شروع نکرده است.", reply_markup=cancel_kb())
        return
    await state.update_data(uid=int(raw))
    p = view.player
    await m.reply(
        f"👤 {p.name} · سطح {p.level} · سکه {p.coins:,} · طلا {p.gold}\n\nچه کاری انجام شود؟",
        reply_markup=kb(
            [("🪙 سکه", "adm_gk:coins"), ("🏅 طلا", "adm_gk:gold"), ("⭐ XP", "adm_gk:xp")],
            [("🐾 حیوان نبرد", "adm_gk:pet"), ("♻️ ریست کامل", "adm_gk:reset")],
            [("🔙 لغو", "adm_cancel")],
        ),
    )


@admin_router.callback_query(F.data.startswith("adm_gk:"), AdminSetup.grant_user)
async def grant_kind(cq: types.CallbackQuery, state: FSMContext) -> None:
    kind = cq.data.split(":", 1)[1]
    d = await state.get_data()
    uid = d.get("uid")
    if not uid:
        await cq.answer("اول آیدی را بفرستید.", show_alert=True)
        return
    if kind == "reset":
        await edit(cq, f"⚠️ مطمئنید که پیشرفت کاربر {uid} کاملاً پاک شود؟", kb([("✅ بله، ریست شود", "adm_gconfirm_reset")], [("🔙 لغو", "adm_cancel")]))
    elif kind == "pet":
        await state.set_state(AdminSetup.grant_amount)
        await state.update_data(kind="pet")
        await edit(cq, "شماره‌ی کاراکتر حیوان (۱ تا ۴) را بفرستید:", cancel_kb())
    else:
        await state.set_state(AdminSetup.grant_amount)
        await state.update_data(kind=kind)
        await edit(cq, "مقدار را بفرستید (برای کم کردن، عدد منفی):", cancel_kb())
    await cq.answer()


@admin_router.callback_query(F.data == "adm_gconfirm_reset", AdminSetup.grant_user)
async def grant_reset(cq: types.CallbackQuery, state: FSMContext) -> None:
    uid = (await state.get_data()).get("uid")
    res = await admin_reset(int(uid))
    await state.clear()
    await edit(cq, ("✅ بازیکن ریست شد." if res.ok else f"❌ {res.msg}") + "\n\nپنل مدیریت:", players_kb())
    await cq.answer()


@admin_router.message(F.text, AdminSetup.grant_amount)
async def receive_grant_amount(m: types.Message, state: FSMContext) -> None:
    d = await state.get_data()
    raw = m.text.strip().replace(",", "")
    if not raw.lstrip("-").isdigit():
        await m.reply("❌ فقط عدد.", reply_markup=cancel_kb())
        return
    amount, uid, kind = int(raw), int(d["uid"]), d["kind"]
    if kind == "pet":
        if amount not in CHARACTERS:
            await m.reply("❌ عدد ۱ تا ۴.", reply_markup=cancel_kb())
            return
        done = await grant_pet(uid, amount)
        msg = f"✅ حیوان «{CHARACTERS[amount].pet_name}» به کاربر داده شد." if done else "❌ ناموفق."
    else:
        kwargs = {kind: amount}
        res = await admin_grant(uid, **kwargs)
        msg = "✅ انجام شد." if res.ok else f"❌ {res.msg}"
    await state.clear()
    await m.reply(f"{msg}\n\nپنل مدیریت:", reply_markup=players_kb())


# ==========================================================================
# Entry point
# ==========================================================================

async def on_error(event: ErrorEvent) -> bool:
    log.exception("unhandled error in update handler", exc_info=event.exception)
    return True


class PremiumSession(AiohttpSession):
    """Everything sent through aiogram (admin panel, shop, replies) passes the same
    premium-only filter as the raw client: plain emoji become premium, buttons get a
    colour and an icon, alerts lose emoji, and a rejected premium payload is retried plain."""

    @staticmethod
    def _decorate(markup):
        if isinstance(markup, types.InlineKeyboardMarkup):
            rows = [[b.model_copy(update=decorate_button({
                "text": b.text, "icon_custom_emoji_id": b.icon_custom_emoji_id, "style": b.style,
            })) for b in row] for row in markup.inline_keyboard]
            return markup.model_copy(update={"inline_keyboard": rows})
        if isinstance(markup, types.ReplyKeyboardMarkup):
            rows = [[b.model_copy(update=decorate_button({
                "text": b.text, "icon_custom_emoji_id": b.icon_custom_emoji_id, "style": b.style,
            })) for b in row] for row in markup.keyboard]
            return markup.model_copy(update={"keyboard": rows})
        return markup

    @classmethod
    def _patch(cls, method):
        fields = type(method).model_fields
        update: dict = {}
        if getattr(method, "__api_method__", "") == "answerCallbackQuery":
            if getattr(method, "text", None):
                update["text"] = strip_emoji(method.text)
        else:
            mode = getattr(method, "parse_mode", None)
            has_entities = bool(getattr(method, "entities", None) or getattr(method, "caption_entities", None))
            for key in ("text", "caption"):
                value = getattr(method, key, None)
                if key not in fields or not isinstance(value, str) or has_entities or "parse_mode" not in fields:
                    continue
                if isinstance(mode, str):
                    if mode.upper() == "HTML":
                        update[key] = premiumize(value)
                else:
                    update[key] = premiumize(html.escape(value, quote=False))
                    update["parse_mode"] = "HTML"
            markup = getattr(method, "reply_markup", None)
            if markup is not None:
                update["reply_markup"] = cls._decorate(markup)
        return method.model_copy(update=update) if update else method

    @staticmethod
    def _plain(method):
        update: dict = {}
        for key in ("text", "caption"):
            value = getattr(method, key, None)
            if isinstance(value, str) and "tg-emoji" in value:
                update[key] = strip_premium(value)
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, types.InlineKeyboardMarkup):
            rows = [[b.model_copy(update={"icon_custom_emoji_id": None}) for b in row] for row in markup.inline_keyboard]
            update["reply_markup"] = markup.model_copy(update={"inline_keyboard": rows})
        elif isinstance(markup, types.ReplyKeyboardMarkup):
            rows = [[b.model_copy(update={"icon_custom_emoji_id": None}) for b in row] for row in markup.keyboard]
            update["reply_markup"] = markup.model_copy(update={"keyboard": rows})
        return method.model_copy(update=update) if update else None

    async def make_request(self, bot, method, timeout=None):
        patched = self._patch(method)
        try:
            return await super().make_request(bot, patched, timeout)
        except TelegramBadRequest as exc:
            if any(s in str(exc).lower() for s in BENIGN):
                raise
            plain = self._plain(patched)
            if plain is None:
                raise
            log.warning("%s rejected (%s) - retrying without premium emoji", getattr(method, "__api_method__", "?"), exc)
            return await super().make_request(bot, plain, timeout)


async def main() -> None:
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        log.critical("BOT_TOKEN is not set. Add it to the Railway Variables (or .env locally).")
        sys.exit(1)
    if not ADMIN_IDS:
        log.warning("ADMIN_ID is not set: the «تغییرات» panel and pet-order approval are disabled.")

    await db.connect(DB_PATH)
    log.info("database ready at %s", DB_PATH)
    await tg.start(BOT_TOKEN)

    unknown = await tg.validate_emoji_ids(source_emoji_ids())
    if unknown:
        BAD_IDS.update(unknown)
        log.warning("%d emoji ids are unknown to Telegram and are replaced automatically: %s",
                    len(unknown), ", ".join(sorted(unknown)))

    session = PremiumSession(api=TelegramAPIServer.from_base(TELEGRAM_API_BASE))
    bot = Bot(token=BOT_TOKEN, session=session)
    dp = Dispatcher(storage=MemoryStorage())
    dp.errors.register(on_error)
    dp.include_router(admin_router)
    dp.include_router(shop_router)
    dp.include_router(story_router)

    try:
        me = await bot.get_me()
        runtime.bot_username = me.username or ""
        log.info("started as @%s", runtime.bot_username)
        await bot.set_my_commands([
            BotCommand(command="menu", description="منوی اصلی تاتاروس"),
            BotCommand(command="story", description="شروع بخش داستانی"),
            BotCommand(command="cancel", description="لغو عملیات جاری"),
        ])
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False)
    finally:
        await bot.session.close()
        await tg.close()
        await db.close()
        log.info("shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
