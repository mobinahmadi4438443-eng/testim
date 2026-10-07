"""تاتاروس - everything the player sees: emojis, texts, Telegram client, buttons and screens."""
import asyncio
import html
import json
import logging
import math
import random
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Sequence

import aiohttp
from aiogram import types
from game import *  # noqa: F401,F403

log = logging.getLogger("tatarus")

# Filled at startup (main.py) with the bot username; used for referral and purchase deep links.
runtime = SimpleNamespace(bot_username="")


# ==========================================================================
# Premium emoji pools
# ==========================================================================

_rng = random.Random()


def _ids(blob: str) -> list[str]:
    return [part for part in blob.split() if part.isdigit()]


def e(eid: str, fb: str = "✨") -> str:
    """Render one custom emoji tag. Falls back to the plain emoji when the id is invalid."""
    eid = (eid or "").strip()
    if not eid.isdigit():
        return fb
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


def pick(pool: list[str], fb: str = "✨") -> str:
    return e(_rng.choice(pool), fb)


def parse_emojis(text: str) -> str:
    """Turn bare 18-22 digit ids typed by the admin into <tg-emoji> tags."""
    return re.sub(r'(?<!["\'\d])(\d{18,22})(?!["\'\d])', r'<tg-emoji emoji-id="\1">✨</tg-emoji>', text)


# --------------------------------------------------------------------------
# Pools (ids come from the owner's emoji packs)
# --------------------------------------------------------------------------
SWORDS = _ids("""
5345906988301725409 5343897957219477338 5344032282321660839 5343740353394551254 5345939127541996538
5345800077975792172 5343945962068946147 5345801830322445591 5339298412317680982 5339480720794496201
5339252847009634986 5339142681098497146 5339175846835953172 5339384281598830250 5337004109507634021
5339441125490992832 5343664899409093606 5343804528795888043 5344029267254618312 5343575065873131806
5343533610848787888 5343684759337870545 5344077658651142847 5343988091403150095 5312549330228386165
5312173086798291772 5309894645302472674 5312255996846971972 5312112278651315971 5312134616776221615
5309867758807196685 5312455661286630044 5337054236070945913 5339348100794327796 5339070177755572035
5339082220843869821 5339294302033979728 5339183302899183175 5339525727756786873 5339327622390257552
5339326406914517617 5339265053306691319 5339464687681577733 5339482275572656977 5339336482907792410
5339301362960215370 5337245890396596736 5339411713554948344 5339272294621551735 5339545261268052317
5339020523638663204 5339124113954873370 5339161939731849537 5339436224933305336 5339127734612305195
5339422760210836871 5292000737805508672 5292156748197568253 5291886706423797686 5292244442839818592
5294250927006458085 5291768225455970608 5294326561380539667 5291986109146899888 5339187164074780871
5339494911366438401 5339564631570556895 5339556011571190954 5339470249664227779 5339400800043048625
5339078797754934383 5339130032419808018
""")

CLASH = _ids("""
5958375350550403093 5958490962480077066 5958761283426719331 5958376072104907832 5958511380754601050
5958372885239174716 5958461262781225622 5958816121569154412 5958333805331748627 5958594101824721885
5958546676795840177 5958701364337972534 5958267186094020392 5958665720404383923 5958635874676643966
5958609692556007137 5958795840733583887 5956169116044761371 5958574052917384760 5958621525190908249
5958505857426659267 5958804155790268495 5958353600836015944 5958578863280756877 5958546861479434425
5958487981772773271 5958322028531423656 5958643717286926603 5958428071273961070 5958762662111221332
5956101388705470045 5958281097493092896 5956394859525837952 5958746371300267640 5956379642456708521
5958473597927298471 5958555236665660683 5958581551930283817 5958662262955711244 5958378245358360456
5958808141519919086 5958786662388471763 5958606630244325380 5958618136461711872 5958415641638607251
5958624179480697023 5958318313384711376 5958816276187985125 5958767927741126280 5956195233740887717
5958697640601327320 5958811521659180444 5958715292916913786 5956139016913950646 5958323853892523249
5958823259804800677 5958374998363085969 5958821726501476156 5956193167861619345 5958425438459009592
5958648493290558783 5958286406072669962 5958491847243339451 5958805328316341612 5958455821057661053
5958436287546399537 5958751379232135064 5956080798632253780 5958469818356078547 5958656082497770670
5958753372096961752 5958734521485499030 5958425996804756658 5958355018175223604 5958489244493158920
5958380620475275085 5958343722411234830 5958296061159151394 5958815674892556996 5958460498277047740
5958349602221463724 5958372919598913228 5958786430460238285 5958614541574084997 5958703026490316703
5958782968716597972 5958635183186910109 5958601892895396910 5958493307532220782 5958726142004303569
5958413455500253131 5958494359799207982 5958565712090897025 5958623981912201440 5958374766434851396
5958761257656916349 5958610435585349384 5958404135421220588 5958421950945565580 5958453957041854369
5958674301749041261 5958808923203967006 5958635466654751299 5958272524738369447 5958617131439364150
5958741543757027960 5958675598829165310 5958431283909499160 5958496683376515902 5958438237461550704
5958375260356089602 5960775717577823816 5960889139074177462 5958693113705798820 5960623018605549354
5958301382623631306 5958618737757132565 5961059395872757976
""")

ATTACK = SWORDS + CLASH

BOSS_CALM = _ids("""
6041835812176272191 6041672191102163393 6041613577683478596 5814562360668461990 6037426220793076236
6034844305498053462 6037142916160297263 6034869770359152915 6035078071978040145 6021784649980714158
5832466601856740169 5902433083692424675 5902078924984162779 5902053266849536703 5823642479877953595
5823306201118547272 5823224716999007312 5821195611239621680 5823591777789026184
""")

BOSS_RAGE = _ids("""
6041846334846146779 6041718654058374097 6042000747510373449 6044381950393719705 6043954888910576445
6044216091641650371 6041783959036108382 6044005337596436498 5814222242208291702 5814349630938290521
5814201188278606613 5814272287167225504 5814407819155217383 6021493696011180326 6021679199943665107
6028251384669805758 6021608144004716962 6021628944531331852 6021562582991640411 6021658738719464745
6021695056962918984 6028319150663801330 6021628983186036875 6021717004245801179 6037173869989600175
6037584997144074766 6037183142823990815 6037533659399985698 6037625855167961665 6037185414861691737
5830049329838038364 5830279892272421748 5830356797956824515 5829987701352308591 5832362143957129853
5832605827516602786 5830463935916022778 5832497182023883350 5832207447825063840 5783039353710189750
5782873138475833793 5780765881491529111
""")

BOSS_FRENZY = _ids("""
6021527201051056472 6021422906360208295 6021758124262693708 6021612211338746664 6021750195753064886
5780658176596646924 5780609587631627157 5780382873487939194 5780799816028135079 5780515991704312994
5902324558458789912 5904341217402952011 5902143499817458993 6041761200004406848 6041737710828264758
6044320575311060640 5814620926842511271 6021709896074927282 6037400103096948939 5832631378277050554
5807769659436440096
""")

HURT = _ids("""
6041691913591986795 6042000859179523912 6041824413333070349 6044392984164702858 5814520836924645620
5814403193475440214 5902303676327794955 5902044900253244927 5902097221544844282 6033092182179584491
5780391029630835938 5780426982802069918 5780472805808154449 6041647851522497495 6044152392981684555
5832468856714565877 5832597787337824636 5780585368311045618 5780500766045248867 6021412070157720417
""")

HEAL = _ids("""
5832234939910723678 5832714451534486204 5832448081957755481 5832171382984677587 5832339457939871994
5832724110915935098 5832386152824314068 5830385187690650015 5832415796688591080 5902367744354949987
5902341965961239801 5902000339967548116 5902224326807002983 5902069493235981088 5902337482015382634
5902009110290766704 5902141940744330810 5868727352879485936
""")

SHIELD_UP = _ids("""
5821178830802394121 6028551194861899805 5868656266875769200 5832209440689888510 5830401555811016243
5902009320744164618 6037277554795092711
""")

VICTORY = _ids("""
5823412110717098659 5902236103607327372 6035250678123732466 6032660615275748488 6028315813474211983
6021819739863522194 6021545862683957251 5902206949369322072 5902017914973724584 6041938680937979565
6043895463743069730 6041756952281750531 5832386517896534336 6046103124177853524 6046414371867858867
5830392042458455180 5823324239981189713 5904706985407814472
""")

DEATH = _ids("""
5902163522954993264 6021792969332366876 5830146185645529745 5776165971517512489 5902020242845998190
6023707730177432064 5902034536497159619 5902223076971518530 6042049259165981177 6041969905350220565
5904575735502216858
""")

PETS = _ids("""
6046344887886945492 5902029008874248738 5823592782811373132 5823539873109253063 5821397728105604489
6021544041617824669 6021664734493809149 6021738277218818742 5807686886826712566
""")

LEVELUP = _ids("""
6032660615275748488 5902206949369322072 6041938680937979565 6043895463743069730 6021819739863522194
5830392042458455180 6028315813474211983
""")

# --------------------------------------------------------------------------
# Fixed semantic icons: name -> (emoji id, fallback)
# --------------------------------------------------------------------------
ICONS: dict[str, tuple[str, str]] = {
    "coin": ("6032699501909644905", "🪙"),
    "gold": ("5870839969982976188", "🏅"),
    "xp": ("6039679437945968043", "⭐"),
    "shield": ("6028551194861899805", "🛡"),
    "hp": ("6034966544562265361", "❤️"),
    "dmg": ("5958808923203967006", "⚔️"),
    "sword": ("5958322028531423656", "⚔️"),
    "fist": ("6037163978679916501", "👊"),
    "skull": ("5902163522954993264", "💀"),
    "blood": ("5902324558458789912", "🩸"),
    "pet": ("6046344887886945492", "🐾"),
    "lock": ("5902020242845998190", "🔒"),
    "ok": ("6034853518202903906", "✅"),
    "fire": ("5902206949369322072", "🔥"),
    "bolt": ("6035045142463781504", "⚡"),
    "title": ("5282974228377789040", "🔥"),
    "point": ("5019617635629794161", "👇"),
    "gift": ("5785281906459283269", "🎁"),
    "warn": ("5395695537687123235", "⚠️"),
    "star": ("6039679437945968043", "⭐"),
    "crit": ("6037502185879641476", "💥"),
    "book": ("5832576548724546042", "📖"),
    "knife": ("5830442181906667908", "🔪"),
    "gun": ("5821440987016206884", "🔫"),
}


def ic(name: str) -> str:
    eid, fb = ICONS[name]
    return e(eid, fb)


# Progress bar segments (chained line emojis)
BAR_RED = "5868376419691663420"
BAR_BLACK = "5870807534389957123"
BAR_BLUE = "5868656266875769200"
BAR_ORANGE = "5868587719197724849"
BAR_GREEN = "5868727352879485936"


def bar(current: int, total: int, length: int, fill_id: str, empty_id: str = BAR_BLACK) -> str:
    total = max(total, 1)
    current = max(0, min(current, total))
    filled = int(current * length / total)
    if current > 0 and filled == 0:
        filled = 1
    filled = max(0, min(filled, length))
    return e(fill_id, "▰") * filled + e(empty_id, "▱") * (length - filled)


# ==========================================================================
# Persian log lines and default guide
# ==========================================================================

HIT = (
    "تو <b>{dmg}</b> دمیج زدی، اما {boss} با چشمان خونین <b>{counter}</b> دمیج ضدحمله زد!",
    "تیغه‌ات <b>{dmg}</b> دمیج در تن {boss} فرو رفت؛ در جوابش <b>{counter}</b> دمیج نصیبت شد!",
    "ضربه‌ی <b>{dmg}</b> تایی‌ات هیولا را عقب راند، ولی {boss} با <b>{counter}</b> دمیج پاسخ داد!",
    "{boss} زیر ضربه‌ی <b>{dmg}</b> تایی غرید و همان لحظه <b>{counter}</b> دمیج برگرداند!",
    "<b>{dmg}</b> دمیج به {boss} زدی و پنجه‌اش <b>{counter}</b> دمیج از تو کند!",
)

CRIT = (
    "ضربه‌ی بحرانی! <b>{dmg}</b> دمیج از تیغت چکید؛ {boss} با <b>{counter}</b> دمیج انتقام گرفت!",
    "خونش پاشید! <b>{dmg}</b> دمیج بحرانی زدی ولی {boss} <b>{counter}</b> دمیج پس داد!",
    "کاری‌ترین ضربه‌ی نبرد: <b>{dmg}</b> دمیج! اما {boss} هم <b>{counter}</b> دمیج کوبید!",
)

DODGE = (
    "تو <b>{dmg}</b> دمیج زدی و از ضدحمله‌ی {boss} جاخالی دادی! هیچ آسیبی ندیدی.",
    "<b>{dmg}</b> دمیج زدی و مثل سایه از چنگال {boss} لیز خوردی!",
)

PET = (
    "حیوانت به طرز وحشیانه‌ای <b>{dmg}</b> دمیج وارد کرد! {boss} گیج شد و نتوانست ضدحمله بزند!",
    "حیوان نبرد تو به {boss} پرید و <b>{dmg}</b> دمیج کند! او در این نوبت گیج است و ضدحمله‌ای ندارد!",
)

POWER = (
    "قدرت‌نمایی کردی و <b>{dmg}</b> دمیج زدی! فشار حمله <b>{self}</b> از خونت کم کرد و {boss} هم <b>{counter}</b> دمیج پس زد.",
)

POWER_DODGE = (
    "قدرت‌نمایی کردی و <b>{dmg}</b> دمیج زدی! فشار حمله <b>{self}</b> از خونت کم کرد، ولی از ضدحمله‌ی {boss} جاخالی دادی.",
)

HEAL_LINES = (
    "با <b>{cost}</b> سکه معجون خون نوشیدی! <b>+{amount}</b> HP برگشت. {boss} پوزخند می‌زند...",
    "معجون خون را سر کشیدی و <b>+{amount}</b> HP گرفتی. {boss} آماده‌ی دور بعد است...",
)

SHIELD = (
    "با <b>{cost}</b> سکه سپرت را بازسازی کردی! <b>+{amount}</b> SHD. {boss} عصبانی‌تر شد...",
    "سپر آبی دور تو شکل گرفت (<b>+{amount}</b> SHD). {boss} غرید: «بشکنش!»",
)

PHASE_UP = {
    1: "{boss} خشمگین شد! ضرباتش ۲۵٪ سنگین‌تر شد!",
    2: "{boss} دیوانه شد! ضرباتش ۵۰٪ مرگبارتر است!",
}

PHASE_TAG = {0: "", 1: "خشمگین", 2: "دیوانه"}

DEFEAT_TIPS = (
    "قبل از اینکه خونت از ۴۰٪ کمتر شود معجون بخر.",
    "حیوان نبرد، باس را گیج می‌کند و ضدحمله‌اش را می‌گیرد.",
    "در حالت «دیوانه» ضربه‌ی باس ۵۰٪ سنگین‌تر است؛ سپر پر داشته باش.",
    "سلاحت را ارتقا بده تا ضربه‌های کمتری لازم باشد.",
    "هر روز هدیه‌ی روزانه و تسک‌ها را بگیر؛ سکه‌ی معجون از همین‌جا می‌آید.",
)

GUIDE_PAGES = (
    (
        "📖 <b>راهنمای داستانی · ۱ از ۵</b>\n\n"
        "دنیای فراموش‌شده، زندان گناهکاران است. تو یکی از تبعیدی‌هایی و تنها راه فرار، شکست دادن نگهبانان <b>هفت دروازه</b> است.\n\n"
        "۱) از «ادامه بازی» یکی از ۴ کاراکتر را انتخاب کن؛ هرکدام توانایی ویژه دارند.\n"
        "۲) «شروع» را بزن و دروازه‌ات را انتخاب کن.\n"
        "۳) باس را بکش، جایزه بگیر و دروازه‌ی بعدی را باز کن.\n\n"
        "هر باس خون بیشتر و ضربه‌ی سنگین‌تری دارد؛ پس سطح و سلاحت را قوی نگه دار."
    ),
    (
        "⚔️ <b>راهنمای داستانی · ۲ از ۵ · چرخه‌ی روزگار</b>\n\n"
        "قانون اصلی نبرد: <b>عمل و عکس‌العمل</b>.\n\n"
        "• پنل نبرد همیشه یک «ضربه‌ی آماده» با دمیج رندوم نشان می‌دهد.\n"
        "• تا روی «بزنش» نزنی دمیج ثبت نمی‌شود.\n"
        "• لحظه‌ای که می‌زنی، باس هم ضدحمله می‌کند: اول سپر (SHD) کم می‌شود، بعد خون (HP).\n"
        "• ضربه‌ی بحرانی شانسی است و دمیج بیشتری دارد.\n"
        "• در گروه می‌توانی بنویسی «دمیج» یا «میدان نبرد» تا پنل نبرد باز شود."
    ),
    (
        "🔥 <b>راهنمای داستانی · ۳ از ۵ · اکشن‌ها</b>\n\n"
        "• <b>قدرت‌نمایی:</b> دمیج ×۲، ولی بخشی از خونت کم می‌شود. هر ۳ حرکت یک‌بار.\n"
        "• <b>حمله حیوان:</b> ۴۰۰ تا ۶۰۰ دمیج و باس همان نوبت گیج می‌شود و ضدحمله نمی‌زند. هر ۴ حرکت یک‌بار.\n"
        "• <b>خرید HP:</b> ۵۰۰ سکه و خونت کامل پر می‌شود.\n"
        "• <b>خرید شیلد:</b> ۱,۰۰۰ سکه و سپرت کامل پر می‌شود.\n\n"
        "باس‌ها وقتی به نصف خونشان برسند «خشمگین» و در یک‌چهارم «دیوانه» می‌شوند و محکم‌تر می‌زنند!"
    ),
    (
        "💰 <b>راهنمای داستانی · ۴ از ۵ · اقتصاد</b>\n\n"
        "• <b>سکه:</b> معجون، سپر، خرید و ارتقای سلاح.\n"
        "• <b>XP:</b> لول‌آپ یعنی خون و دمیج بیشتر و پر شدن کامل خون.\n"
        "• <b>طلا:</b> برای خرید کُلت و کلاش؛ باس‌ها طلا می‌دهند.\n"
        "• <b>ارتقا:</b> هر سلاح تا +۱۰ ارتقا می‌خورد.\n"
        "• <b>حیوان نبرد:</b> برای هر کاراکتر جداگانه خریداری می‌شود و از «حیوانات نبرد» فعال می‌شود."
    ),
    (
        "☠️ <b>راهنمای داستانی · ۵ از ۵ · مرگ و پیروزی</b>\n\n"
        "• <b>مرگ:</b> ۲,۰۰۰ سکه جریمه، خونت ریست و باس از نو شروع می‌شود.\n"
        "• اگر وسط نبرد از پنل خارج شوی، نبردت نگه داشته می‌شود و با «ادامه» برمی‌گردی.\n"
        "• <b>پیروزی:</b> سکه، XP و طلای عظیم! (تکرار یک باس، ۳۰٪ جایزه دارد.)\n"
        "• هدیه‌ی روزانه و تسک‌ها را از دست نده.\n"
        "• با لینک دعوت، دوستانت را بیاور و سکه بگیر."
    ),
)


# ==========================================================================
# Raw Telegram client with plain fallback
# ==========================================================================

_TG_EMOJI = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.DOTALL)

# Errors that a plain-text retry cannot fix.
_BENIGN = (
    "message is not modified",
    "message to edit not found",
    "message to delete not found",
    "message can't be edited",
    "message can't be deleted",
    "message to be replied not found",
    "chat not found",
    "bot was blocked",
    "user is deactivated",
    "not enough rights",
    "have no rights",
    "need administrator rights",
    "query is too old",
    "forbidden",
    "message_id_invalid",
    "too many requests",
)


def strip_premium(obj):
    """Return a copy of a payload without custom emoji tags and button icons."""
    if isinstance(obj, str):
        return _TG_EMOJI.sub(r"\1", obj)
    if isinstance(obj, list):
        return [strip_premium(x) for x in obj]
    if isinstance(obj, dict):
        return {k: strip_premium(v) for k, v in obj.items() if k != "icon_custom_emoji_id"}
    return obj


def has_premium(payload) -> bool:
    return "tg-emoji" in json.dumps(payload, ensure_ascii=False) or "icon_custom_emoji_id" in json.dumps(payload)


class Telegram:
    def __init__(self) -> None:
        self.token = ""
        self.session: aiohttp.ClientSession | None = None
        self.plain = PLAIN_MODE
        self.fallbacks = 0

    async def start(self, token: str) -> None:
        self.token = token
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35))

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _post(self, method: str, payload: dict) -> dict:
        assert self.session is not None, "Telegram client is not started"
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/{method}"
        last_exc = ""
        for attempt in range(3):
            try:
                async with self.session.post(url, json=payload) as resp:
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                last_exc = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(0.6 * (attempt + 1))
                continue
            if data.get("ok"):
                return data
            if data.get("error_code") == 429:
                wait = float(data.get("parameters", {}).get("retry_after", 1))
                if wait > 12:
                    return data
                log.warning("flood wait %.1fs on %s", wait, method)
                await asyncio.sleep(wait + 0.3)
                continue
            return data
        return {"ok": False, "error_code": 0, "description": last_exc or "network error"}

    async def call(self, method: str, payload: dict) -> dict:
        if self.plain:
            payload = strip_premium(payload)
        data = await self._post(method, payload)
        if data.get("ok"):
            return data
        desc = str(data.get("description", "")).lower()
        if data.get("error_code") == 400 and not any(s in desc for s in _BENIGN) and has_premium(payload):
            self.fallbacks += 1
            log.warning("%s rejected (%s) - retrying without premium emoji", method, data.get("description"))
            retry = await self._post(method, strip_premium(payload))
            if retry.get("ok"):
                return retry
            data = retry
        if not any(s in str(data.get("description", "")).lower() for s in _BENIGN):
            log.error("Telegram API error [%s]: %s", method, data)
        return data


tg = Telegram()


def ok(result: dict) -> bool:
    return bool(result.get("ok"))


def not_modified(result: dict) -> bool:
    return "message is not modified" in str(result.get("description", "")).lower()


# ==========================================================================
# Buttons, callbacks, media and screen transitions
# ==========================================================================

DEFAULT = object()

# name -> (default icon id, style)   style: primary (blue) | success (green) | danger (red) | None
BUTTONS: dict[str, tuple[str, str | None]] = {
    # main menu
    "حساب کاربری": ("5987865893084861885", "primary"),
    "بازار": ("5258024802010026053", "success"),
    "داستانی": ("5364052602357044385", "danger"),
    "مولتی(چند جهانی)": ("5361741454685256344", "primary"),
    "اسکین": ("5987973065403797894", "primary"),
    "ارتقا": ("5375338737028841420", "success"),
    "ماموریت ها": ("5282996373229167849", "success"),
    "جنگ ها": ("5453991094435997597", "danger"),
    "بازار سیاه": ("5296387887984580731", "danger"),
    "فروشگاه": ("5406683434124859552", "success"),
    "لیدربرد": ("5415655814079723871", "primary"),
    "کلن": ("5978687277390371946", "primary"),
    "اخبار": ("5443038326535759644", "primary"),
    "راهنما": ("5282843764451195532", "primary"),
    "بستن منو": ("5210952531676504517", "danger"),
    # story
    "ادامه بازی": ("5206607081334906820", "success"),
    "شروع": ("6021608144004716962", "danger"),
    "ادامه": ("6037142916160297263", "primary"),
    "تسک": ("5780382873487939194", "primary"),
    "جوایز روزانه": ("6034834521562553211", "success"),
    "حیوانات نبرد": ("6042051380879822629", "primary"),
    "راهنمای داستانی": ("6039577350868310365", "primary"),
    "بستن": ("6032606743500951856", "danger"),
    "بازگشت": ("6041794945562451034", None),
    "منوی داستانی": ("5282974228377789040", None),
    # battle
    "بریم تو دل مبارزه": ("6034966544562265361", "danger"),
    "ادامه نبرد": ("6034966544562265361", "danger"),
    "بزنش": ("5958322028531423656", "danger"),
    "قدرت‌نمایی": ("6037163978679916501", "danger"),
    "حمله حیوان": ("6042051380879822629", "primary"),
    "خرید HP": ("6032699501909644905", "success"),
    "خرید شیلد": ("6028551194861899805", "primary"),
    "دوباره تلاش کن": ("6021608144004716962", "danger"),
    "دروازه‌ها": ("5902020242845998190", "primary"),
    "دروازه بعدی": ("6021608144004716962", "danger"),
    # upgrade
    "چاقو": ("5830442181906667908", None),
    "شمشیر": ("5785098292312415025", None),
    "کُلت": ("6034845503793928402", None),
    "کلاش": ("5181902025721381896", None),
    "خرید سلاح": ("6032699501909644905", "success"),
    "ارتقای سلاح": ("5375338737028841420", "success"),
    "تجهیز سلاح": ("5361741454685256344", "primary"),
    # daily / tasks / pets
    "دریافت جوایز روزانه": ("6028565819225542441", "success"),
    "دریافت جایزه تسک": ("6028565819225542441", "success"),
    "فعال کردن برای نبرد": ("5780857858216173092", "success"),
    "غیرفعال کردن حیوان": ("6032606743500951856", "danger"),
    "خریدن حیوان": ("6028565819225542441", "success"),
    "قبلی": ("5210952531676504517", "primary"),
    "بعدی": ("5210952531676504517", "primary"),
}


def button_names() -> list[str]:
    return list(BUTTONS)


def btn(name: str, data: str | None = None, *, label: str | None = None, style=DEFAULT, icon: str | None = None, url: str | None = None) -> dict:
    default_icon, default_style = BUTTONS.get(name, ("", None))
    icon_id = icon or get_setting(f"emoji_{name}") or default_icon
    out: dict = {"text": label or name}
    if url:
        out["url"] = url
    else:
        assert data is not None and len(data.encode()) <= 64, f"bad callback data: {data!r}"
        out["callback_data"] = data
    if icon_id and str(icon_id).strip().isdigit():
        out["icon_custom_emoji_id"] = str(icon_id).strip()
    final_style = default_style if style is DEFAULT else style
    if final_style:
        out["style"] = final_style
    return out


# ------------------------------------------------------------------ callbacks
def cb(action: str, uid: int, *args) -> str:
    return ":".join(["g", action, *[str(a) for a in args], str(uid)])


def parse_cb(data: str | None) -> tuple[str, list[str], int] | None:
    if not data or not data.startswith("g:"):
        return None
    parts = data.split(":")
    if len(parts) < 3 or not parts[-1].lstrip("-").isdigit():
        return None
    return parts[1], parts[2:-1], int(parts[-1])


# ----------------------------------------------------------------- text utils
def esc(value: str) -> str:
    return html.escape(value or "", quote=False)


def visible_len(text: str) -> int:
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def text_override(key: str, legacy: str | None = None) -> str | None:
    raw = get_setting(f"text_{key}") or (get_setting(legacy) if legacy else None)
    return parse_emojis(raw) if raw else None


def fmt_time(seconds: int) -> str:
    h, rem = divmod(max(0, seconds), 3600)
    m = rem // 60
    if h:
        return f"{h} ساعت و {m} دقیقه"
    return f"{max(1, m)} دقیقه"


# ---------------------------------------------------------------------- media
def pick_media(keys: Sequence[str]) -> tuple[str, str, str] | None:
    for key in keys:
        fid = get_setting(f"photo_{key}")
        if fid:
            return fid, get_setting(f"type_{key}", "photo"), get_setting(f"uniq_{key}", "")
    return None


def _message_has_media(msg: types.Message) -> bool:
    return bool(msg.photo or msg.video or msg.animation or msg.document)


def _message_unique_id(msg: types.Message) -> str:
    if msg.photo:
        return msg.photo[-1].file_unique_id
    if msg.animation:
        return msg.animation.file_unique_id
    if msg.video:
        return msg.video.file_unique_id
    if msg.document:
        return msg.document.file_unique_id
    return ""


_SEND_METHOD = {"photo": ("sendPhoto", "photo"), "video": ("sendVideo", "video"), "animation": ("sendAnimation", "animation")}


async def delete_message(chat_id: int, message_id: int) -> None:
    await tg.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


async def send_new(
    chat_id: int,
    keys: Sequence[str],
    text: str,
    kb: list[list[dict]],
    *,
    reply_to: int | None = None,
    thread_id: int | None = None,
) -> int | None:
    """Send a fresh screen (media + caption if configured, otherwise text). Returns the message id."""
    text = _fit(text)
    media = pick_media(keys)
    if media and visible_len(text) > 1024:
        log.warning("caption too long (%d) - sending text only for %s", visible_len(text), list(keys))
        media = None
    base: dict = {"chat_id": chat_id, "parse_mode": "HTML", "reply_markup": {"inline_keyboard": kb}}
    if reply_to:
        base["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    if thread_id:
        base["message_thread_id"] = thread_id

    if media:
        fid, mtype, _ = media
        method, field = _SEND_METHOD.get(mtype, _SEND_METHOD["photo"])
        res = await tg.call(method, {**base, field: fid, "caption": text})
        if ok(res):
            return res["result"]["message_id"]
        log.warning("media send failed (%s) - falling back to text", res.get("description"))
    res = await tg.call("sendMessage", {**base, "text": text, "link_preview_options": {"is_disabled": True}})
    return res["result"]["message_id"] if ok(res) else None


def _fit(text: str) -> str:
    if len(text) <= 4096:
        return text
    log.warning("text longer than 4096 chars was truncated")
    return text[:4000] + "…"


async def show(msg: types.Message, keys: Sequence[str], text: str, kb: list[list[dict]]) -> None:
    """Transition the existing panel to a new screen with the fewest visible side-effects."""
    text = _fit(text)
    media = pick_media(keys)
    if media and visible_len(text) > 1024:
        log.warning("caption too long (%d) - text-only fallback for %s", visible_len(text), list(keys))
        media = None
    has_media = _message_has_media(msg)
    chat_id, mid = msg.chat.id, msg.message_id
    markup = {"inline_keyboard": kb}

    if media:
        fid, mtype, uniq = media
        if has_media:
            if uniq and uniq == _message_unique_id(msg):
                res = await tg.call("editMessageCaption", {
                    "chat_id": chat_id, "message_id": mid, "caption": text, "parse_mode": "HTML", "reply_markup": markup,
                })
            else:
                res = await tg.call("editMessageMedia", {
                    "chat_id": chat_id, "message_id": mid, "reply_markup": markup,
                    "media": {"type": mtype, "media": fid, "caption": text, "parse_mode": "HTML"},
                })
            if ok(res) or not_modified(res):
                return
    else:
        if not has_media:
            res = await tg.call("editMessageText", {
                "chat_id": chat_id, "message_id": mid, "text": text, "parse_mode": "HTML",
                "reply_markup": markup, "link_preview_options": {"is_disabled": True},
            })
            if ok(res) or not_modified(res):
                return

    reply_to = msg.reply_to_message.message_id if msg.reply_to_message else None
    thread_id = msg.message_thread_id if getattr(msg, "is_topic_message", False) else None
    new_id = await send_new(chat_id, keys, text, kb, reply_to=reply_to, thread_id=thread_id)
    if new_id:
        await delete_message(chat_id, mid)


# ==========================================================================
# Screens (media keys, HTML text, keyboard)
# ==========================================================================

BAR_LEN = 10


@dataclass
class Screen:
    keys: list[str]
    text: str
    kb: list[list[dict]]


# ------------------------------------------------------------------ helpers
def char_plain(cid: int) -> str:
    default = CHARACTERS[cid].default_name
    raw = get_setting(f"char{cid}_name") or default
    return re.sub(r"\d{15,22}", "", raw).split("=")[0].strip() or default


def char_name(cid: int) -> str:
    return esc(char_plain(cid))


def char_icon(cid: int) -> str:
    eid = get_setting(f"char{cid}_emoji") or CHARACTERS[cid].default_emoji
    return e(eid, "🗡")


def boss_icon(boss: Boss) -> str:
    return e(*boss.icon)


def weapon_icon(key: str) -> str:
    return e(*WEAPONS[key].icon)


def weapon_label(key: str, up: int) -> str:
    w = WEAPONS[key]
    return f"{w.name} +{up}" if up else w.name


def n(value: int) -> str:
    return f"{value:,}"


def back_row(uid: int, to: str = "menu", label: str = "بازگشت") -> list[dict]:
    return [btn("بازگشت", cb(to, uid), label=label)]


def avg_strike(v: View) -> float:
    st = v.stats
    return v.weapon_dmg * 1.025 * (1 + st.crit_chance * (st.crit_mult - 1))


def hits_needed(v: View, boss_hp: int) -> int:
    return max(1, math.ceil(boss_hp / max(1.0, avg_strike(v))))


# --------------------------------------------------------------- main menu
def main_screen(uid: int) -> Screen:
    text = text_override("main_menu") or (
        f"{ic('title')} <b>منوی اصلی بازی تاتاروس</b>\n\n{ic('point')} بخش مورد نظر خود را انتخاب کنید:"
    )
    soon = lambda name: cb("soon", uid, name)  # noqa: E731
    kb = [
        [btn("حساب کاربری", cb("profile", uid)), btn("بازار", soon("market"))],
        [btn("داستانی", cb("story", uid)), btn("مولتی(چند جهانی)", soon("multi"))],
        [btn("اسکین", soon("skin")), btn("ارتقا", cb("upg", uid))],
        [btn("ماموریت ها", cb("tasks", uid))],
        [btn("جنگ ها", soon("wars")), btn("بازار سیاه", soon("black"))],
        [btn("فروشگاه", soon("shop")), btn("لیدربرد", cb("top", uid))],
        [btn("کلن", soon("clan")), btn("اخبار", soon("news"))],
        [btn("راهنما", cb("guide", uid, 1)), btn("بستن منو", cb("close", uid))],
    ]
    return Screen(["main"], text, kb)


def story_screen(uid: int) -> Screen:
    text = text_override("story_intro") or (
        f"سلام {e('5296480809602023717', '👋')}\n"
        f"به دنیای <b>تاتاروس</b> خوش آمدی {e('5296349143084595007', '🔥')}\n\n"
        "اینجا «دنیای فراموش‌شده» است؛ زندانی در دل تاریکی که گناهکاران و تبعیدشدگان همه‌ی دنیاها به آن پرتاب می‌شوند. "
        "هر که اینجا افتاد، یا می‌جنگد... یا برای همیشه گم می‌شود. "
        f"{e('5296785692150497491', '💀')}\n\n"
        f"تنها راه فرار، عبور از <b>هفت دروازه‌ی خونین</b> و کشتن نگهبانانشان است؛ از دراخور بی‌رحم تا خودِ ارباب تاتاروس. {e('5453991094435997597', '⚔️')}\n\n"
        f"در نبرد، «چرخه‌ی روزگار» حاکم است: هر ضربه‌ای که بزنی، همان لحظه ضدحمله می‌خوری. "
        f"برای زنده ماندن به {ic('coin')} سکه (معجون و سپر)، {ic('xp')} XP (قوی‌تر شدن) و {ic('gold')} طلا (سلاح‌های سنگین‌تر) نیاز داری.\n\n"
        f"{e('5395695537687123235', '⚠️')} اولین دشمنت <b>دراخور</b> است: <code>15,000</code> HP و ضرباتی ۱۰۰ تا ۳۰۰ دمیجی. "
        "بی‌نقشه نرو؛ تسک‌ها، هدیه‌ی روزانه و دعوت دوستان سکه‌ی مبارزه‌ات را می‌سازند. "
        f"{e('5440660757194744323', '😈')}"
    )
    kb = [[btn("ادامه بازی", cb("chars", uid)), btn("بازگشت", cb("main", uid))]]
    return Screen(["story"], text, kb)


# ---------------------------------------------------------------- characters
def chars_screen(uid: int, v: View) -> Screen:
    head = text_override("char_select") or f"{ic('point')} <b>کاراکترت را انتخاب کن</b>"
    rows = []
    for cid, ch in CHARACTERS.items():
        mark = " ✅" if v.player.char_id == cid else ""
        rows.append(f"{char_icon(cid)} <b>{char_name(cid)}</b>{mark} — {ch.perk_title}: <i>{ch.perk_desc}</i>")
    text = head + "\n\nهر کاراکتر یک توانایی ویژه دارد:\n\n" + "\n".join(rows)
    buttons = []
    for cid in CHARACTERS:
        eid = get_setting(f"char{cid}_emoji") or CHARACTERS[cid].default_emoji
        mark = "✅ " if v.player.char_id == cid else ""
        buttons.append(btn("بازگشت", cb("pick", uid, cid), label=f"{mark}{char_plain(cid)}",
                           icon=eid, style="success" if v.player.char_id == cid else "primary"))
    kb = [buttons[:2], buttons[2:], [btn("بازگشت", cb("story", uid))]]
    return Screen(["character"], text, kb)


# ---------------------------------------------------------------- game menu
def game_menu_screen(uid: int, v: View, daily_ready: bool) -> Screen:
    p = v.player
    head = text_override("game_menu") or f"{ic('title')} <b>منوی داستانی تاتاروس</b>"
    boss = BOSSES[min(p.unlocked, LAST_BOSS)]
    status = f"{ic('skull')} دروازه‌ی فعلی: {boss_icon(boss)} <b>{boss.name}</b> ({p.unlocked} از {LAST_BOSS})"
    if v.battle:
        cur = BOSSES[v.battle.boss_id]
        status = (f"{ic('fist')} نبرد در جریان: {boss_icon(cur)} <b>{cur.name}</b> — "
                  f"<code>{n(v.battle.boss_hp)}</code> / <code>{n(cur.hp)}</code> HP")
    text = (
        f"{head}\n\n"
        f"{char_icon(p.char_id)} <b>{char_name(p.char_id)}</b> · سطح <code>{p.level}</code>\n"
        f"{ic('coin')} <code>{n(p.coins)}</code>  {ic('gold')} <code>{p.gold}</code>  {ic('xp')} <code>{n(p.xp)}/{n(xp_needed(p.level))}</code>\n"
        f"{status}\n\n"
        f"{ic('point')} بخش مورد نظر خود را انتخاب کنید:"
    )
    daily_label = "جوایز روزانه" + (" 🎁" if daily_ready else "")
    kb = [
        [btn("شروع", cb("gates", uid)), btn("ادامه", cb("cont", uid))],
        [btn("ارتقا", cb("upg", uid)), btn("تسک", cb("tasks", uid))],
        [btn("جوایز روزانه", cb("daily", uid), label=daily_label, style="success" if daily_ready else None),
         btn("حیوانات نبرد", cb("pets", uid))],
        [btn("راهنمای داستانی", cb("guide", uid, 1), label="راهنما"), btn("بستن", cb("close", uid))],
    ]
    return Screen(["gamemenu"], text, kb)


# --------------------------------------------------------------------- gates
def gates_screen(uid: int, v: View) -> Screen:
    p = v.player
    lines_ = []
    buttons = []
    for boss in BOSSES.values():
        kills = v.kills.get(boss.id, 0)
        if boss.id > p.unlocked:
            lines_.append(f"{ic('lock')} <b>دروازه‌ی {boss.id}</b> — <i>؟؟؟ (قفل)</i>")
            buttons.append(btn("دروازه‌ها", cb("locked", uid, boss.id), label=f"دروازه {boss.id}", icon=_lock_id(), style=None))
            continue
        mark = f"{ic('ok')}" if kills else f"{ic('fist')}"
        lines_.append(f"{mark} {boss_icon(boss)} <b>{boss.name}</b> — <code>{n(boss.hp)}</code> HP"
                      + (f" · <i>کشته‌شده ×{kills}</i>" if kills else ""))
        buttons.append(btn("دروازه‌ها", cb("boss", uid, boss.id), label=boss.name, icon=boss.icon[0],
                           style="success" if kills else "danger"))
    text = (f"{ic('title')} <b>دروازه‌های تاتاروس</b>\n\n" + "\n".join(lines_) +
            f"\n\n{ic('point')} دروازه‌ای را که می‌خواهی بگشایی انتخاب کن:")
    kb = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    kb.append(back_row(uid))
    return Screen(["gamestart"], text, kb)


def _lock_id() -> str:
    return ICONS["lock"][0]


def boss_screen(uid: int, v: View, boss: Boss) -> Screen:
    hits = hits_needed(v, boss.hp)
    w = WEAPONS[boss.weapon_hint]
    resume = v.battle is not None and v.battle.boss_id == boss.id
    text = (
        f"{ic('warn')} <b>توجه</b> {ic('warn')}\n"
        f"مبارز، تو در آستانه‌ی <b>دروازه‌ی {boss.id}</b> ایستاده‌ای!\n\n"
        f"حریف: {boss_icon(boss)} <b>{boss.name}</b> — <i>{boss.title}</i>\n"
        f"{boss.lore}\n\n"
        f"{ic('hp')} HP: <code>{n(boss.hp)}</code>   {ic('fist')} DMG: <code>{boss.dmg_min} - {boss.dmg_max}</code>\n"
        f"{ic('coin')} جایزه: <code>{n(boss.coins)}</code> سکه · <code>{n(boss.xp)}</code> XP · <code>{boss.gold}</code> طلا\n"
        f"{weapon_icon(boss.weapon_hint)} سلاح پیشنهادی: <b>{w.name}</b>\n\n"
        f"{ic('sword')} با <b>{weapon_label(v.player.weapon, v.weapon_up)}</b> (حدود <code>{n(int(avg_strike(v)))}</code> دمیج) "
        f"حدود <code>{hits}</code> ضربه لازم داری.\n"
        "قانون چرخه: هر ضربه‌ی تو یک ضدحمله‌ی او. معجون و سپر یادت نره!"
    )
    if resume:
        text += f"\n\n{ic('fire')} نبرد نیمه‌کاره‌ات هنوز هست: <code>{n(v.battle.boss_hp)}</code> HP از او مانده."
    elif v.battle:
        other = BOSSES[v.battle.boss_id]
        text += f"\n\n{ic('warn')} ورود به این دروازه، نبرد نیمه‌کاره‌ات با <b>{other.name}</b> را از بین می‌برد."
    kb = [
        [btn("ادامه نبرد" if resume else "بریم تو دل مبارزه", cb("fight", uid, boss.id))],
        [btn("بازگشت", cb("gates", uid))],
    ]
    return Screen([f"boss_{boss.id}", "gamestart"], text, kb)


# --------------------------------------------------------------------- arena
def _pet_status(v: View) -> str:
    b = v.battle
    if not v.pet_owned:
        return "<i>نداری</i>"
    if not v.pet_active:
        return "<i>غیرفعال</i>"
    if b and b.pet_cd > 0:
        return f"<i>⏳ {b.pet_cd} حرکت</i>"
    return "<b>آماده</b>"


def arena_screen(uid: int, v: View, log: str = "") -> Screen:
    b, p, st = v.battle, v.player, v.stats
    assert b is not None
    boss = BOSSES[b.boss_id]
    phase = phase_of(b.boss_hp, boss.hp)
    tag = ""
    if phase == 1:
        tag = f" · {pick(BOSS_RAGE, '😠')} <b>خشمگین</b>"
    elif phase == 2:
        tag = f" · {pick(BOSS_FRENZY, '🩸')} <b>دیوانه</b>"
    if not log:
        log = f"{pick(BOSS_CALM, '😏')} <i>{_rng.choice(boss.taunts)}</i>"
    pet_icon = e(*CHARACTERS[p.char_id].pet_icon)
    crit_tag = f" {ic('crit')} <b>بحرانی!</b>" if b.pending_crit else ""
    text = (
        f"{ic('sword')} <b>میدان نبرد · دروازه‌ی {boss.id}</b> {ic('sword')}\n\n"
        f"{boss_icon(boss)} <b>{boss.name}</b>{tag}\n"
        f"{ic('hp')} HP: {bar(b.boss_hp, boss.hp, BAR_LEN, BAR_ORANGE)} <code>{n(b.boss_hp)} / {n(boss.hp)}</code>\n"
        f"{ic('fist')} DMG: <code>{boss.dmg_min} - {boss.dmg_max}</code>\n\n"
        f"{char_icon(p.char_id)} <b>{char_name(p.char_id)}</b> · Lv <code>{p.level}</code>\n"
        f"{ic('hp')} HP: {bar(p.hp, st.max_hp, BAR_LEN, BAR_RED)} <code>{n(p.hp)} / {n(st.max_hp)}</code>\n"
        f"{ic('shield')} SHD: {bar(p.shield, st.max_shield, BAR_LEN, BAR_BLUE)} <code>{n(p.shield)} / {n(st.max_shield)}</code>\n"
        f"{ic('xp')} XP: {bar(p.xp, xp_needed(p.level), BAR_LEN, BAR_GREEN)} <code>{n(p.xp)} / {n(xp_needed(p.level))}</code>\n\n"
        f"{weapon_icon(p.weapon)} سلاح: <code>{weapon_label(p.weapon, v.weapon_up)}</code> | {ic('dmg')} آسیب: <code>{n(v.weapon_dmg)}</code>\n"
        f"{ic('coin')} سکه: <code>{n(p.coins)}</code> | {ic('gold')} طلا: <code>{p.gold}</code>\n"
        f"{pet_icon} حیوان: {_pet_status(v)}\n\n"
        f"{ic('fist')} <b>ضربه‌ی آماده:</b> <code>{n(b.pending)}</code> دمیج{crit_tag}\n"
        f"┈┈┈┈┈┈┈┈┈┈┈\n{log}"
    )
    power_ready = b.power_cd <= 0
    pet_ready = v.pet_owned and v.pet_active and b.pet_cd <= 0
    hp_full = p.hp >= st.max_hp
    sh_full = p.shield >= st.max_shield
    kb = [
        [btn("بزنش", cb("act", uid, "hit", b.round), label=f"بزنش · {n(b.pending)}")],
        [
            btn("قدرت‌نمایی", cb("act", uid, "power", b.round),
                label="قدرت‌نمایی" + ("" if power_ready else f" · ⏳{b.power_cd}"), style="danger" if power_ready else None),
            btn("حمله حیوان", cb("act", uid, "pet", b.round),
                label="حمله حیوان" + ("" if pet_ready or not (v.pet_owned and v.pet_active) else f" · ⏳{b.pet_cd}"),
                style="primary" if pet_ready else None),
        ],
        [
            btn("خرید HP", cb("act", uid, "heal", 0), label=f"خرید HP · {n(HEAL_COST)}", style=None if hp_full else "success"),
            btn("خرید شیلد", cb("act", uid, "shield", 0), label=f"خرید شیلد · {n(SHIELD_COST)}", style=None if sh_full else "primary"),
        ],
        [btn("بازگشت", cb("menu", uid), label="بازگشت به منو داستانی")],
    ]
    return Screen(["battle"], text, kb)


def battle_log(out: Outcome) -> str:
    boss = out.boss
    assert boss is not None
    name = f"<b>{boss.name}</b>"
    if out.phase == 0:
        mood = pick(BOSS_CALM, "😏")
    elif out.phase == 1:
        mood = pick(BOSS_RAGE, "😠")
    else:
        mood = pick(BOSS_FRENZY, "🩸")
    atk = pick(ATTACK, "⚔️")
    a = out.action
    if a == "heal":
        return f"{pick(HEAL, '😌')} <i>{_rng.choice(HEAL_LINES).format(cost=n(out.cost), amount=n(out.amount), boss=name)}</i>"
    if a == "shield":
        return f"{pick(SHIELD_UP, '🛡')} <i>{_rng.choice(SHIELD).format(cost=n(out.cost), amount=n(out.amount), boss=name)}</i>"

    d = dict(dmg=n(out.dmg), counter=n(out.counter), boss=name, self=n(out.self_dmg), absorbed=n(out.absorbed))
    if a == "pet":
        body = _rng.choice(PET).format(**d)
        head = pick(PETS, "🐾")
    elif a == "power":
        body = _rng.choice(POWER_DODGE if out.dodged else POWER).format(**d)
        head = pick(ATTACK, "⚔️")
    else:
        pool = DODGE if out.dodged else (CRIT if out.crit else HIT)
        body = _rng.choice(pool).format(**d)
        head = atk
    if out.absorbed and out.counter:
        body += " (سپر همه‌اش را خورد)" if out.absorbed >= out.counter else f" (سپر <b>{n(out.absorbed)}</b> را جذب کرد)"
    parts = [f"{head} <i>{body}</i> {mood}"]
    if out.phase_up:
        parts.append(f"{pick(BOSS_FRENZY if out.phase == 2 else BOSS_RAGE, '🔥')} <b>{PHASE_UP[out.phase].format(boss=boss.name)}</b>")
    if out.levelups:
        parts.append(f"{pick(LEVELUP, '⭐')} <b>سطحت به {out.view.player.level} رسید!</b> خونت پر شد.")
    return "\n".join(parts)


def enter_log(boss: Boss, replaced: bool) -> str:
    log = f"{pick(BOSS_CALM, '😏')} <i>{_rng.choice(boss.taunts)}</i>"
    if replaced:
        log += "\n<i>(نبرد قبلی‌ات رها شد.)</i>"
    return log


# ------------------------------------------------------------------- results
def victory_screen(uid: int, out: Outcome) -> Screen:
    boss, v = out.boss, out.view
    assert boss is not None and v is not None
    text = (
        f"{pick(VICTORY, '😎')} <b>پیروزی!</b> {pick(VICTORY, '😎')}\n\n"
        f"{boss_icon(boss)} <b>{boss.name}</b> بر خاک افتاد!\n<i>{boss.death}</i>\n\n"
        f"{ic('coin')} <b>+{n(out.reward_coins)}</b> سکه\n"
        f"{ic('xp')} <b>+{n(out.reward_xp + out.xp_gain)}</b> XP\n"
    )
    if out.reward_gold:
        text += f"{ic('gold')} <b>+{out.reward_gold}</b> طلا\n"
    if not out.first_kill:
        text += "<i>(جایزه‌ی تکرار باس: ۳۰٪ سکه و ۵۰٪ XP)</i>\n"
    if out.levelups:
        text += f"\n{pick(LEVELUP, '⭐')} <b>سطحت به {v.player.level} رسید!</b> خونت پر شد."
    nxt = BOSSES.get(out.unlocked_new) if out.unlocked_new else None
    if nxt:
        text += f"\n{ic('lock')} <b>دروازه‌ی {nxt.id} گشوده شد:</b> {boss_icon(nxt)} {nxt.name}"
    if out.game_complete:
        text += (f"\n\n{pick(VICTORY, '😎')} <b>تاتاروس شکست خورد!</b> دیوارهای دنیای فراموش‌شده فرو ریخت و تو فرار کردی. "
                 "افسانه‌ی این دنیا حالا نام تو را می‌خواند!")
    text += f"\n\n{ic('coin')} موجودی: <code>{n(v.player.coins)}</code> · {ic('gold')} <code>{v.player.gold}</code>"
    kb = []
    if nxt:
        kb.append([btn("دروازه بعدی", cb("boss", uid, nxt.id), label=f"دروازه‌ی بعدی · {nxt.name}", icon=nxt.icon[0])])
    else:
        kb.append([btn("دروازه‌ها", cb("gates", uid), label="دروازه‌ها")])
    kb.append([btn("ارتقا", cb("upg", uid), label="ارتقای سلاح"), btn("منوی داستانی", cb("menu", uid))])
    return Screen(["victory", "gamemenu"], text, kb)


def defeat_screen(uid: int, out: Outcome) -> Screen:
    boss, v = out.boss, out.view
    assert boss is not None and v is not None
    text = (
        f"{pick(DEATH, '💀')} <b>در میدان کشته شدی!</b> {pick(DEATH, '💀')}\n\n"
        f"{boss_icon(boss)} <b>{boss.name}</b> با خنده‌ای وحشیانه بالای سرت ایستاد و جسمت را به تاریکی سپرد...\n\n"
        f"{ic('coin')} <b>{n(out.penalty)}</b> سکه به‌عنوان جریمه از دست دادی.\n"
        f"{ic('hp')} خونت ریست شد؛ نبرد از نو شروع می‌شود.\n\n"
        f"{pick(HURT, '😰')} <i>نکته: {_rng.choice(DEFEAT_TIPS)}</i>\n\n"
        f"{ic('coin')} موجودی: <code>{n(v.player.coins)}</code>"
    )
    kb = [
        [btn("دوباره تلاش کن", cb("boss", uid, boss.id))],
        [btn("منوی داستانی", cb("menu", uid))],
    ]
    return Screen(["defeat", "gamemenu"], text, kb)


# ------------------------------------------------------------------- upgrade
def upgrade_screen(uid: int, v: View) -> Screen:
    p = v.player
    head = text_override("upgrade_intro") or f"{ic('title')} <b>کارگاه سلاح‌ها</b>"
    rows = []
    for key in WEAPON_ORDER:
        w = WEAPONS[key]
        if key in v.weapons:
            up = v.weapons[key]
            state = "✅ در دست" if p.weapon == key else "در انبار"
            rows.append(f"{weapon_icon(key)} <b>{w.name}</b> (L{w.tier}) +{up} — دمیج <code>{n(weapon_damage(key, up))}</code> · {state}")
        else:
            price = f"{n(w.price_coins)} سکه" + (f" + {w.price_gold} طلا" if w.price_gold else "")
            rows.append(f"{ic('lock')} <b>{w.name}</b> (L{w.tier}) — دمیج <code>{n(w.dmg)}</code> · خرید: <code>{price}</code>")
    text = (
        f"{head}\n\n{ic('coin')} <code>{n(p.coins)}</code>  {ic('gold')} <code>{p.gold}</code>\n\n"
        + "\n".join(rows)
        + f"\n\n{ic('point')} روی هر سلاح بزن تا بخری، ارتقا بدهی یا برداری."
    )
    names = {"knife": "چاقو", "sword": "شمشیر", "colt": "کُلت", "ak47": "کلاش"}
    kb = []
    for key in WEAPON_ORDER:
        owned = key in v.weapons
        style = "success" if p.weapon == key else ("primary" if owned else None)
        kb.append([btn(names[key], cb("wpn", uid, key), style=style)])
    kb.append(back_row(uid))
    return Screen(["upgrade"], text, kb)


def weapon_screen(uid: int, v: View, key: str) -> Screen:
    w = WEAPONS[key]
    p = v.player
    owned = key in v.weapons
    up = v.weapons.get(key, 0)
    mult = v.stats.dmg_mult
    lines_ = [f"{weapon_icon(key)} <b>{w.name}</b> (L{w.tier})", ""]
    if owned:
        lines_.append(f"سطح ارتقا: <code>+{up}</code> از <code>+{WEAPON_UP_MAX}</code>")
        lines_.append(f"دمیج پایه: <code>{n(weapon_damage(key, up))}</code> → با ضرایب تو: <code>{n(int(weapon_damage(key, up) * mult))}</code>")
        if up < WEAPON_UP_MAX:
            cost = upgrade_cost(key, up)
            lines_.append(f"ارتقای بعدی: <code>{n(cost)}</code> سکه → دمیج <code>{n(weapon_damage(key, up + 1))}</code>")
        else:
            lines_.append("به <b>حداکثر ارتقا</b> رسیده است!")
        lines_.append("وضعیت: " + ("✅ در دست تو" if p.weapon == key else "در انبار"))
    else:
        price = f"<code>{n(w.price_coins)}</code> سکه" + (f" + <code>{w.price_gold}</code> طلا" if w.price_gold else "")
        lines_.append(f"دمیج پایه: <code>{n(w.dmg)}</code>")
        lines_.append(f"قیمت خرید: {price}")
        lines_.append(f"موجودی تو: {ic('coin')} <code>{n(p.coins)}</code> · {ic('gold')} <code>{p.gold}</code>")
    kb = []
    if not owned:
        kb.append([btn("خرید سلاح", cb("wbuy", uid, key), label=f"خرید · {n(w.price_coins)}")])
    else:
        if up < WEAPON_UP_MAX:
            kb.append([btn("ارتقای سلاح", cb("wup", uid, key), label=f"ارتقا به +{up + 1} · {n(upgrade_cost(key, up))}")])
        if p.weapon != key:
            kb.append([btn("تجهیز سلاح", cb("wequip", uid, key), label="برداشتن در دست")])
    kb.append([btn("بازگشت", cb("upg", uid))])
    return Screen([f"weapon_{key}", "upgrade"], "\n".join(lines_), kb)


# --------------------------------------------------------------------- daily
def daily_screen(uid: int, status: dict, result: dict | None = None) -> Screen:
    c = DAILY_COINS
    x = DAILY_XP
    text = f"{ic('gift')} <b>هدیه‌ی روزانه</b>\n\n"
    if result:
        text += (
            f"{ic('ok')} <b>دریافت شد!</b>\n\n"
            f"{ic('coin')} <b>+{n(result['coins'])}</b> سکه\n"
            f"{ic('xp')} <b>+{result['xp']}</b> XP\n"
        )
        if result.get("gold"):
            text += f"{ic('gold')} <b>+{result['gold']}</b> طلا (جایزه‌ی استریک هفتم!)\n"
        text += f"\n{ic('fire')} استریک: <code>{result['streak']}</code> روز پشت‌سر‌هم"
    elif status["ready"]:
        text += (
            f"{ic('ok')} هدیه‌ی امروز آماده است!\n\n"
            f"{ic('coin')} <code>{n(c[0])} - {n(c[1])}</code> سکه (رندوم)\n"
            f"{ic('xp')} <code>{x[0]} - {x[1]}</code> XP\n"
            f"{ic('fire')} استریک: <code>{status['streak']}</code> روز · هر روز پشت‌سر‌هم ۱۰٪ جایزه‌ی بیشتر (تا ۶ روز) و روز هفتم یک طلا!\n\n"
            f"{ic('point')} برای گرفتنش دکمه‌ی دریافت را بزن!"
        )
    else:
        text += (
            f"{ic('lock')} جایزه‌ی امروز را گرفته‌ای.\n"
            f"⏳ هدیه‌ی بعدی: <b>{fmt_time(status['wait'])}</b> دیگر\n"
            f"{ic('fire')} استریک: <code>{status['streak']}</code> روز"
        )
    kb = []
    if status["ready"] and not result:
        kb.append([btn("دریافت جوایز روزانه", cb("claimd", uid))])
    kb.append(back_row(uid))
    return Screen(["gamedaily"], text, kb)


# --------------------------------------------------------------------- tasks
def tasks_screen(uid: int, v: View, tasks: list[dict]) -> Screen:
    text = f"{ic('book')} <b>تسک‌های امروز</b> <i>(نیمه‌شب ریست می‌شوند)</i>\n\n"
    kb = []
    for t in tasks:
        task: Task = t["task"]
        reward = f"{n(task.coins)} سکه" + (f" + {task.gold} طلا" if task.gold else "") + f" + {task.xp} XP"
        if t["claimed"]:
            mark = "✅"
        elif t["done"]:
            mark = "🎁"
        else:
            mark = "⏳"
        text += (f"{mark} <b>{task.title}</b>\n"
                 f"   {bar(t['progress'], task.target, 5, BAR_GREEN)} <code>{n(t['progress'])}/{n(task.target)}</code> · {reward}\n")
        if t["done"] and not t["claimed"]:
            kb.append([btn("دریافت جایزه تسک", cb("claimt", uid, task.key), label=f"دریافت: {task.title}")])
    link = f"https://t.me/{runtime.bot_username}?start=ref_{uid}" if runtime.bot_username else "—"
    text += (
        f"\n{ic('gift')} <b>دعوت دوستان</b>\nلینک اختصاصی تو:\n<code>{link}</code>\n"
        f"هر دعوت: <code>{n(REFERRAL_INVITER_COINS)}</code> سکه + <code>{REFERRAL_INVITER_XP}</code> XP · "
        f"دعوت‌شده‌ها: <code>{v.player.ref_count}</code>"
    )
    kb.append(back_row(uid))
    return Screen(["tasks", "gamemenu"], text, kb)


# ---------------------------------------------------------------------- pets
def pets_screen(uid: int, v: View) -> Screen:
    p = v.player
    ch = CHARACTERS[p.char_id]
    icon = e(*ch.pet_icon)
    owned = v.pet_owned
    custom = text_override("pet_text", legacy="pet_text")
    body = custom or f"{icon} <b>{ch.pet_name}</b> — همراه {char_icon(p.char_id)} <b>{char_name(p.char_id)}</b>\n<i>{ch.pet_lore}</i>"
    body += (f"\n\n{ic('fist')} دمیج: <code>{PET_DMG[0]} - {PET_DMG[1]}</code> (+{int(PET_LEVEL_BONUS * 100)}٪ به‌ازای هر سطح)\n"
             f"{pick(BOSS_CALM, '😏')} باس در همان نوبت گیج می‌شود و ضدحمله نمی‌زند · هر <code>{PET_COOLDOWN}</code> حرکت یک‌بار")
    if owned:
        state = "فعال برای نبرد" if v.pet_active else "غیرفعال"
        body += f"\n\n{ic('ok')} <b>خریداری شده</b> · وضعیت: {state}"
    else:
        body += f"\n\n{ic('lock')} <b>خریداری نشده</b>"
    others = [cid for cid in v.pets if cid != p.char_id]
    if others:
        body += "\n<i>حیوانات دیگر تو: " + "، ".join(CHARACTERS[c].pet_name for c in sorted(others)) + "</i>"
    kb = []
    if owned:
        if v.pet_active:
            kb.append([btn("غیرفعال کردن حیوان", cb("petog", uid, p.char_id))])
        else:
            kb.append([btn("فعال کردن برای نبرد", cb("petog", uid, p.char_id))])
    else:
        url = f"https://t.me/{runtime.bot_username}?start=buypet_{p.char_id}"
        kb.append([btn("خریدن حیوان", None, url=url)])
    kb.append(back_row(uid))
    return Screen([f"pet_{p.char_id}", "gamemenu"], body, kb)


# --------------------------------------------------------------------- guide
def guide_page_count() -> int:
    custom = int(get_setting("guide_pages_count", "0") or 0)
    return custom if custom > 0 else len(GUIDE_PAGES)


def guide_screen(uid: int, page: int) -> Screen:
    total = guide_page_count()
    page = max(1, min(page, total))
    custom = int(get_setting("guide_pages_count", "0") or 0) > 0
    if custom:
        raw = get_setting(f"guide_text_{page}") or "متن راهنما تنظیم نشده است."
        text = parse_emojis(raw)
    else:
        text = GUIDE_PAGES[page - 1]
    nav = []
    if page > 1:
        nav.append(btn("قبلی", cb("guide", uid, page - 1)))
    if page < total:
        nav.append(btn("بعدی", cb("guide", uid, page + 1)))
    kb = []
    if nav:
        kb.append(nav)
    kb.append(back_row(uid))
    return Screen([f"guide_{page}", "gamemenu"], text, kb)


# ------------------------------------------------------------ profile / top
def profile_screen(uid: int, v: View, rank: tuple[int, int]) -> Screen:
    p, st = v.player, v.stats
    ch = CHARACTERS[p.char_id]
    text = (
        f"{ic('title')} <b>پرونده‌ی تبعیدی</b>\n\n"
        f"{char_icon(p.char_id)} <b>{esc(p.name)}</b>" + (f" · @{esc(p.username)}" if p.username else "") + "\n"
        f"کاراکتر: <b>{char_name(p.char_id)}</b> ({ch.perk_title})\n"
        f"رتبه: <code>#{rank[0]}</code> از <code>{rank[1]}</code>\n\n"
        f"{ic('star')} سطح <code>{p.level}</code> · {bar(p.xp, xp_needed(p.level), 8, BAR_GREEN)} <code>{n(p.xp)}/{n(xp_needed(p.level))}</code>\n"
        f"{ic('hp')} HP: <code>{n(p.hp)}/{n(st.max_hp)}</code> · {ic('shield')} SHD: <code>{n(p.shield)}/{n(st.max_shield)}</code>\n"
        f"{ic('coin')} <code>{n(p.coins)}</code>  {ic('gold')} <code>{p.gold}</code>\n"
        f"{weapon_icon(p.weapon)} سلاح: <b>{weapon_label(p.weapon, v.weapon_up)}</b> · دمیج <code>{n(v.weapon_dmg)}</code>\n\n"
        f"{ic('skull')} دروازه‌ی بازشده: <code>{p.unlocked}/{LAST_BOSS}</code> · باس‌کشی: <code>{p.kills}</code> · مرگ: <code>{p.deaths}</code>\n"
        f"{ic('fist')} ضربات: <code>{n(p.strikes)}</code> · بحرانی: <code>{n(p.crits)}</code> · حمله حیوان: <code>{n(p.pet_uses)}</code>\n"
        f"{ic('dmg')} کل دمیج: <code>{n(p.damage_total)}</code>"
    )
    return Screen(["profile"], text, [back_row(uid, "main")])


def leaderboard_screen(uid: int, players: list, rank: tuple[int, int]) -> Screen:
    medals = ["🥇", "🥈", "🥉"]
    rows = []
    for i, p in enumerate(players):
        mark = medals[i] if i < 3 else f"<code>{i + 1}.</code>"
        rows.append(f"{mark} {char_icon(p.char_id)} <b>{esc(p.name)}</b> — سطح <code>{p.level}</code> · دروازه <code>{p.unlocked}</code> · باس <code>{p.kills}</code>")
    text = f"{ic('title')} <b>لیدربرد تاتاروس</b>\n\n" + ("\n".join(rows) if rows else "هنوز کسی وارد نشده است.")
    text += f"\n\n{ic('fist')} رتبه‌ی تو: <code>#{rank[0]}</code> از <code>{rank[1]}</code>"
    return Screen(["leaderboard", "main"], text, [back_row(uid, "main")])


SOON_TEXT = "⏳ این بخش به‌زودی در چرخه‌ی روزگار گشوده می‌شود..."
