"""تاتاروس - game logic: config, rules/content, database and the battle engine (no Telegram code here)."""
import asyncio
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone

import aiosqlite
from dotenv import load_dotenv

log = logging.getLogger("tatarus")


# ==========================================================================
# Config (environment)
# ==========================================================================

load_dotenv()


def _parse_ids(*raws: str) -> frozenset[int]:
    ids: set[int] = set()
    for raw in raws:
        for part in (raw or "").replace(";", ",").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                ids.add(int(part))
    return frozenset(ids)


def _resolve_db_path() -> str:
    explicit = os.getenv("DB_PATH", "").strip()
    if explicit:
        path = explicit
    else:
        volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
        path = os.path.join(volume, "tatarus.db") if volume else "tatarus.db"
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    return path


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS: frozenset[int] = _parse_ids(os.getenv("ADMIN_IDS", ""), os.getenv("ADMIN_ID", ""))
DB_PATH: str = _resolve_db_path()

# Set PLAIN_MODE=1 to force normal emojis (no premium emoji / no button icons).
PLAIN_MODE: bool = os.getenv("PLAIN_MODE", "").strip().lower() in {"1", "true", "yes"}

# Only used by the automated tests (local mock of the Telegram API).
TELEGRAM_API_BASE: str = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")

# Iran has no DST anymore, so a fixed offset is enough and needs no tzdata package.
TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


# ==========================================================================
# Rules, balance and content data
# ==========================================================================

# ----------------------------------------------------------------- economy
START_COINS = 12_500
START_GOLD = 0
HEAL_COST = 500
SHIELD_COST = 1_000
DEATH_PENALTY = 2_000
REFERRAL_INVITER_COINS = 5_000
REFERRAL_INVITER_XP = 50
REFERRAL_INVITEE_COINS = 2_500
REPEAT_COIN_PCT = 0.30
REPEAT_XP_PCT = 0.50

# ------------------------------------------------------------------ combat
BASE_HP = 1_600
HP_PER_LEVEL = 100
BASE_SHIELD = 600
SHIELD_PER_LEVEL = 30
MAX_LEVEL = 100
DMG_PER_LEVEL = 0.02

STRIKE_VARIANCE = (0.90, 1.15)
BASE_CRIT_CHANCE = 0.08
BASE_CRIT_MULT = 1.75

POWER_MULT = 2.0
POWER_COOLDOWN = 3
POWER_SELF_PCT = (0.06, 0.10)

PET_DMG = (400, 600)
PET_LEVEL_BONUS = 0.03
PET_COOLDOWN = 4

STRIKE_XP = (2, 5)
PET_XP = 4

# boss damage multiplier by phase: 0 normal, 1 rage (<=50% hp), 2 frenzy (<=25% hp)
PHASE_MULT = (1.0, 1.25, 1.5)

WEAPON_UP_MAX = 10
WEAPON_UP_BONUS = 0.08

# Consecutive strikes that never cost you HP build a combo (the shield keeps it alive).
COMBO_MAX = 10
COMBO_BONUS = 0.015


def xp_needed(level: int) -> int:
    return 500 + (level - 1) * 350


def max_hp(level: int) -> int:
    return BASE_HP + HP_PER_LEVEL * (level - 1)


def phase_of(boss_hp: int, boss_max: int) -> int:
    if boss_max <= 0:
        return 0
    ratio = boss_hp / boss_max
    if ratio <= 0.25:
        return 2
    if ratio <= 0.50:
        return 1
    return 0


# -------------------------------------------------------------- characters
@dataclass(frozen=True)
class Character:
    id: int
    default_name: str
    default_emoji: str
    perk_title: str
    perk_desc: str
    pet_name: str
    pet_icon: tuple[str, str]
    pet_lore: str
    dmg_mult: float = 1.0
    crit_bonus: float = 0.0
    crit_mult: float = BASE_CRIT_MULT
    dodge: float = 0.0
    shield_mult: float = 1.0


CHARACTERS: dict[int, Character] = {
    1: Character(
        1, "زولو", "5832457500821034730",
        "تیغ‌دار", "۱۲٪ دمیج بیشتر در همه‌ی ضربه‌ها",
        "سایه‌گرگ", ("6046344887886945492", "🐺"),
        "گرگی که از دل مه بیرون آمد. چشم‌هایش مثل زغال می‌سوزد و گلوی هر دشمنی را نشانه می‌رود.",
        dmg_mult=1.12,
    ),
    2: Character(
        2, "نورا", "5958487981772773271",
        "سایه", "۱۵٪ شانس جاخالی از ضدحمله‌ی باس",
        "شبح‌پلنگ", ("5902029008874248738", "🐆"),
        "پلنگی بی‌صدا که فقط وقتی دیده می‌شود که دیگر دیر شده است.",
        dodge=0.15,
    ),
    3: Character(
        3, "جسپر", "5780382873487939194",
        "نگهبان", "۴۰٪ ظرفیت سپر بیشتر",
        "خرس آهنین", ("5821397728105604489", "🐻"),
        "خرسی زره‌پوش با پنجه‌هایی که سنگ را خرد می‌کند و ضربه‌ای را پس نمی‌دهد.",
        shield_mult=1.40,
    ),
    4: Character(
        4, "رکس", "6034966544562265361",
        "وحشی", "۱۲٪ شانس بحرانی بیشتر و ضربه‌ی بحرانی ×۲",
        "گوزن شاخ‌خون", ("5807686886826712566", "🦌"),
        "شاخ‌هایش با خون دشمنان قبلی رنگ شده؛ وقتی می‌تازد، زمین می‌لرزد.",
        crit_bonus=0.12, crit_mult=2.0,
    ),
}


# ----------------------------------------------------------------- weapons
@dataclass(frozen=True)
class Weapon:
    key: str
    name: str
    tier: int
    dmg: int
    price_coins: int
    price_gold: int
    upgrade_base: int
    icon: tuple[str, str]


WEAPONS: dict[str, Weapon] = {
    "knife": Weapon("knife", "چاقو", 1, 150, 0, 0, 2_000, ("5830442181906667908", "🔪")),
    "sword": Weapon("sword", "شمشیر", 2, 300, 35_000, 0, 6_000, ("5345906988301725409", "🗡")),
    "colt": Weapon("colt", "کُلت", 3, 600, 120_000, 3, 15_000, ("5821440987016206884", "🔫")),
    "ak47": Weapon("ak47", "کلاش", 4, 1_200, 350_000, 8, 40_000, ("6035097914726947384", "🔫")),
}
WEAPON_ORDER = ("knife", "sword", "colt", "ak47")


def weapon_damage(key: str, up: int) -> int:
    w = WEAPONS.get(key) or WEAPONS["knife"]
    return int(w.dmg * (1 + WEAPON_UP_BONUS * max(0, up)))


def upgrade_cost(key: str, up: int) -> int:
    w = WEAPONS[key]
    return w.upgrade_base * (up + 1)


# ------------------------------------------------------------------ bosses
@dataclass(frozen=True)
class Boss:
    id: int
    name: str
    title: str
    hp: int
    dmg_min: int
    dmg_max: int
    coins: int
    xp: int
    gold: int
    icon: tuple[str, str]
    weapon_hint: str
    lore: str
    taunts: tuple[str, ...]
    death: str


BOSSES: dict[int, Boss] = {
    1: Boss(
        1, "دراخور", "هیولای بی‌رحم دروازه‌ی اول", 15_000, 100, 300, 50_000, 300, 1,
        ("6037533659399985698", "😈"), "knife",
        "از تاریک‌ترین نقطه‌ی دنیای وِراث به تاتاروس تبعید شده. اولین نگهبان این زندان است و تا امروز هیچ تبعیدی زنده از زیر چنگالش رد نشده.",
        ("دراخور با چشمانی خونین به تو خیره شده است...", "نفس گرمِ دراخور بوی گوشت سوخته می‌دهد و خنده‌اش در غار می‌پیچد."),
        "غرشِ آخرِ دراخور در غار پیچید و جسم عظیمش مثل کوه فرو ریخت. اولین دروازه به رویت باز شد!",
    ),
    2: Boss(
        2, "نکروثا", "ملکه‌ی استخوان‌ها", 32_000, 160, 380, 110_000, 550, 2,
        ("6037502439282712379", "👾"), "sword",
        "فرمانروای گورستان‌های بی‌پایان. هر که را بکشد به لشکر استخوانی‌اش می‌افزاید و ضربه‌هایش از هر تیغی سردتر و بُرنده‌تر است.",
        ("استخوان‌های زیر پای نکروثا با هر قدمش آواز می‌خوانند...", "تاج نکروثا از جمجمه‌ی تبعیدی‌های قبلی ساخته شده و حالا به تو لبخند می‌زند."),
        "تاج جمجمه‌ایِ نکروثا ترک خورد و لشکر استخوان‌ها با ناله‌ای خاموش شدند. ملکه برای همیشه آرام گرفت!",
    ),
    3: Boss(
        3, "ورگال", "جلاد زنجیرها", 60_000, 220, 520, 220_000, 900, 3,
        ("6035097914726947384", "👿"), "colt",
        "آهنگر زنجیرهای تبعید. هر ضربه‌ی چکش او حکم محکومیتی است که با خون امضا شده و هیچ سپری جلوی آن را نمی‌گیرد.",
        ("زنجیرهای ورگال روی زمین کشیده می‌شوند و جرقه می‌زنند...", "ورگال چکشش را بالا می‌برد؛ سایه‌اش تمام میدان را می‌بلعد."),
        "چکش ورگال از دستش افتاد و زنجیرهای تبعید یکی‌یکی از هم گسستند. جلاد، خودش اسیر زنجیرهایش شد!",
    ),
    4: Boss(
        4, "مالکوروس", "پادشاه خاکستر", 100_000, 300, 680, 400_000, 1_400, 5,
        ("6034869770359152915", "👹"), "ak47",
        "شهری را سوزاند تا بر خاکسترش تخت بسازد. شعله‌هایش حتی سپرهای آهنین را آب می‌کند.",
        ("مالکوروس روی تخت خاکستر نشسته و از بالا به تو نگاه می‌کند...", "هر نفسِ مالکوروس جرقه‌ای از آتش جهنم است."),
        "تخت خاکستر فروریخت و شعله‌های مالکوروس برای همیشه خاموش شدند. پادشاهی که شهری را سوزاند، خودش سوخت!",
    ),
    5: Boss(
        5, "ایزرا", "سایه‌ی بی‌چهره", 160_000, 400, 850, 700_000, 2_100, 7,
        ("5829994341371747297", "😈"), "ak47",
        "کسی چهره‌اش را ندیده و زنده نمانده. از تاریکی می‌زند و در تاریکی ناپدید می‌شود.",
        ("ایزرا هیچ‌جا نیست... و همه‌جا هست.", "صدایی در گوشت زمزمه می‌کند: «تو هم تبعید شدی...» — ایزرا است."),
        "سایه‌ی ایزرا اولین بار صورتی پیدا کرد؛ صورتی که از ترس منجمد شده بود. و بعد برای همیشه محو شد!",
    ),
    6: Boss(
        6, "بعل‌زرگ", "خدای خشم", 240_000, 520, 1_050, 1_100_000, 3_000, 10,
        ("6037584997144074766", "🤬"), "ak47",
        "خشم تبعیدی‌های هزارساله در جسمی از آهن و آتش. هیچ ضعفی ندارد جز صبر کسی که تا اینجا زنده مانده.",
        ("زمین زیر پای بعل‌زرگ ترک برمی‌دارد و آسمان سرخ می‌شود...", "غرش بعل‌زرگ دیوارهای دنیای فراموش‌شده را می‌لرزاند."),
        "خدای خشم زانو زد و آتش هزارساله‌اش در چشم‌هایش خاموش شد. آسمان سرخ، برای اولین بار آرام گرفت!",
    ),
    7: Boss(
        7, "تاتاروس", "ارباب دنیای فراموش‌شده", 400_000, 700, 1_400, 2_500_000, 5_000, 25,
        ("6044381950393719705", "😡"), "ak47",
        "پایان هر راه و زندانبان اصلی این دنیا. فقط کسی که او را بکشد می‌تواند از دنیای فراموش‌شده فرار کند.",
        ("تاریکی دور تو حلقه می‌زند... تاتاروس منتظرت بود.", "«هر که آمد، ماند.» — تاتاروس می‌خندد."),
        "ارباب دنیای فراموش‌شده فروپاشید و دیوارهای زندان ترک برداشتند. نوری از دور می‌تابد... راه فرار گشوده شد!",
    ),
}
LAST_BOSS = max(BOSSES)


# ------------------------------------------------------------------- tasks
@dataclass(frozen=True)
class Task:
    key: str
    title: str
    target: int
    coins: int
    xp: int
    gold: int = 0


TASKS: tuple[Task, ...] = (
    Task("hits", "۲۵ ضربه بزن", 25, 2_000, 20),
    Task("damage", "۵,۰۰۰ دمیج به باس‌ها وارد کن", 5_000, 3_000, 30),
    Task("crit", "۳ ضربه‌ی بحرانی بزن", 3, 2_000, 20),
    Task("heal", "۲ بار معجون خون بخر", 2, 1_500, 10),
    Task("shield", "۱ بار سپر بخر", 1, 1_500, 10),
    Task("kill", "۱ باس را شکست بده", 1, 10_000, 100, 1),
)
TASKS_BY_KEY = {t.key: t for t in TASKS}

DAILY_COINS = (500, 3_000)
DAILY_XP = (10, 60)
DAILY_STREAK_BONUS = 0.10
DAILY_STREAK_CAP = 6
DAILY_GOLD_EVERY = 7


# ==========================================================================
# SQLite storage
# ==========================================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS players (
    user_id      INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL DEFAULT '',
    username     TEXT    NOT NULL DEFAULT '',
    char_id      INTEGER NOT NULL DEFAULT 1,
    coins        INTEGER NOT NULL DEFAULT 0,
    gold         INTEGER NOT NULL DEFAULT 0,
    xp           INTEGER NOT NULL DEFAULT 0,
    level        INTEGER NOT NULL DEFAULT 1,
    hp           INTEGER NOT NULL DEFAULT 1,
    shield       INTEGER NOT NULL DEFAULT 0,
    weapon       TEXT    NOT NULL DEFAULT 'knife',
    unlocked     INTEGER NOT NULL DEFAULT 1,
    kills        INTEGER NOT NULL DEFAULT 0,
    deaths       INTEGER NOT NULL DEFAULT 0,
    strikes      INTEGER NOT NULL DEFAULT 0,
    crits        INTEGER NOT NULL DEFAULT 0,
    pet_uses     INTEGER NOT NULL DEFAULT 0,
    damage_total INTEGER NOT NULL DEFAULT 0,
    last_daily   TEXT    NOT NULL DEFAULT '',
    streak       INTEGER NOT NULL DEFAULT 0,
    referred_by  INTEGER NOT NULL DEFAULT 0,
    ref_count    INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL DEFAULT 0,
    last_seen    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_players_rank ON players (unlocked DESC, level DESC, xp DESC);

CREATE TABLE IF NOT EXISTS weapons (
    user_id INTEGER NOT NULL,
    key     TEXT    NOT NULL,
    up      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS pets (
    user_id INTEGER NOT NULL,
    char_id INTEGER NOT NULL,
    active  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, char_id)
);

CREATE TABLE IF NOT EXISTS boss_kills (
    user_id INTEGER NOT NULL,
    boss_id INTEGER NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, boss_id)
);

CREATE TABLE IF NOT EXISTS battles (
    user_id     INTEGER PRIMARY KEY,
    boss_id     INTEGER NOT NULL DEFAULT 1,
    boss_hp     INTEGER NOT NULL DEFAULT 0,
    round       INTEGER NOT NULL DEFAULT 1,
    pending     INTEGER NOT NULL DEFAULT 0,
    pending_crit INTEGER NOT NULL DEFAULT 0,
    pet_cd      INTEGER NOT NULL DEFAULT 0,
    power_cd    INTEGER NOT NULL DEFAULT 0,
    started_at  INTEGER NOT NULL DEFAULT 0,
    combo       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    user_id  INTEGER NOT NULL,
    day      TEXT    NOT NULL,
    key      TEXT    NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    claimed  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, key)
);

CREATE TABLE IF NOT EXISTS pet_orders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    char_id    INTEGER NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'pending',
    phone      TEXT    NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL DEFAULT 0,
    decided_at INTEGER NOT NULL DEFAULT 0,
    decided_by INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON pet_orders (user_id, char_id, status);
"""


class Tx:
    """Connection handle that is only valid inside `Database.tx()` (lock already held)."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def execute(self, sql: str, params: tuple = ()) -> int:
        async with self._conn.execute(sql, params) as cur:
            return cur.rowcount

    async def insert(self, sql: str, params: tuple = ()) -> int:
        async with self._conn.execute(sql, params) as cur:
            return cur.lastrowid or 0

    async def fetchone(self, sql: str, params: tuple = ()):
        async with self._conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        async with self._conn.execute(sql, params) as cur:
            return await cur.fetchall()


class Database:
    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self.settings: dict[str, str] = {}

    async def connect(self, path: str) -> None:
        self._conn = await aiosqlite.connect(path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        async with self._conn.execute("PRAGMA table_info(battles)") as cur:
            battle_cols = {row["name"] async for row in cur}
        if "combo" not in battle_cols:
            await self._conn.execute("ALTER TABLE battles ADD COLUMN combo INTEGER NOT NULL DEFAULT 0")
        async with self._conn.execute("SELECT key, value FROM settings") as cur:
            self.settings = {row["key"]: row["value"] async for row in cur}
        log.info("database ready at %s (%d settings)", path, len(self.settings))

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @asynccontextmanager
    async def tx(self):
        assert self._conn is not None, "database is not connected"
        async with self._lock:
            await self._run("BEGIN IMMEDIATE")
            try:
                yield Tx(self._conn)
            except BaseException:
                try:
                    await self._run("ROLLBACK")
                except Exception:
                    log.exception("rollback failed")
                raise
            else:
                await self._run("COMMIT")

    async def _run(self, sql: str) -> None:
        assert self._conn is not None
        async with self._conn.execute(sql):
            pass

    # ----- settings (served from memory, persisted on write) -----
    def get(self, key: str, default=None):
        return self.settings.get(key, default)

    async def set(self, key: str, value: str) -> None:
        async with self.tx() as tx:
            await tx.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        self.settings[key] = value

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        async with self.tx() as tx:
            for key in keys:
                await tx.execute("DELETE FROM settings WHERE key = ?", (key,))
        for key in keys:
            self.settings.pop(key, None)

    async def delete_prefix(self, prefix: str) -> None:
        keys = [k for k in self.settings if k.startswith(prefix)]
        await self.delete(*keys)


db = Database()


def get_setting(key: str, default=None):
    return db.get(key, default)


async def set_setting(key: str, value: str) -> None:
    await db.set(key, value)


# ==========================================================================
# Models
# ==========================================================================

PLAYER_FIELDS = (
    "name", "username", "char_id", "coins", "gold", "xp", "level", "hp", "shield", "weapon",
    "unlocked", "kills", "deaths", "strikes", "crits", "pet_uses", "damage_total",
    "last_daily", "streak", "referred_by", "ref_count", "created_at", "last_seen",
)

BATTLE_FIELDS = ("boss_id", "boss_hp", "round", "pending", "pending_crit", "pet_cd", "power_cd", "started_at", "combo")


@dataclass
class Player:
    user_id: int
    name: str = ""
    username: str = ""
    char_id: int = 1
    coins: int = 0
    gold: int = 0
    xp: int = 0
    level: int = 1
    hp: int = 1
    shield: int = 0
    weapon: str = "knife"
    unlocked: int = 1
    kills: int = 0
    deaths: int = 0
    strikes: int = 0
    crits: int = 0
    pet_uses: int = 0
    damage_total: int = 0
    last_daily: str = ""
    streak: int = 0
    referred_by: int = 0
    ref_count: int = 0
    created_at: int = 0
    last_seen: int = 0

    @classmethod
    def from_row(cls, row) -> "Player":
        names = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in names})

    async def save(self, tx: Tx) -> None:
        sets = ", ".join(f"{name} = ?" for name in PLAYER_FIELDS)
        values = tuple(getattr(self, name) for name in PLAYER_FIELDS)
        await tx.execute(f"UPDATE players SET {sets} WHERE user_id = ?", values + (self.user_id,))


@dataclass
class Battle:
    user_id: int
    boss_id: int = 1
    boss_hp: int = 0
    round: int = 1
    pending: int = 0
    pending_crit: int = 0
    pet_cd: int = 0
    power_cd: int = 0
    started_at: int = 0
    combo: int = 0

    @classmethod
    def from_row(cls, row) -> "Battle":
        names = {f.name for f in fields(cls)}
        return cls(**{k: row[k] for k in row.keys() if k in names})

    async def save(self, tx: Tx) -> None:
        sets = ", ".join(f"{name} = ?" for name in BATTLE_FIELDS)
        values = tuple(getattr(self, name) for name in BATTLE_FIELDS)
        await tx.execute(f"UPDATE battles SET {sets} WHERE user_id = ?", values + (self.user_id,))


# ==========================================================================
# Game engine (every public coroutine is one atomic transaction)
# ==========================================================================

rng = random.Random()


# ------------------------------------------------------------------ helpers
def now_ts() -> int:
    return int(time.time())


def _now_tehran() -> datetime:
    return datetime.now(TEHRAN_TZ)


def today_key() -> str:
    return _now_tehran().strftime("%Y-%m-%d")


def yesterday_key() -> str:
    return (_now_tehran() - timedelta(days=1)).strftime("%Y-%m-%d")


def seconds_to_midnight() -> int:
    now = _now_tehran()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


@dataclass
class Stats:
    max_hp: int
    max_shield: int
    dmg_mult: float
    crit_chance: float
    crit_mult: float
    dodge: float


def derive(p: Player) -> Stats:
    ch = CHARACTERS.get(p.char_id, CHARACTERS[1])
    lvl = max(1, p.level)
    return Stats(
        max_hp=max_hp(lvl),
        max_shield=int((BASE_SHIELD + SHIELD_PER_LEVEL * (lvl - 1)) * ch.shield_mult),
        dmg_mult=(1 + DMG_PER_LEVEL * (lvl - 1)) * ch.dmg_mult,
        crit_chance=min(0.60, BASE_CRIT_CHANCE + ch.crit_bonus),
        crit_mult=ch.crit_mult,
        dodge=ch.dodge,
    )


def apply_xp(p: Player, gain: int) -> int:
    """Add XP, level up as needed. Returns how many levels were gained."""
    p.xp += max(0, gain)
    gained = 0
    while p.level < MAX_LEVEL and p.xp >= xp_needed(p.level):
        p.xp -= xp_needed(p.level)
        p.level += 1
        gained += 1
    if p.level >= MAX_LEVEL:
        p.xp = min(p.xp, xp_needed(MAX_LEVEL) - 1)
    if gained:
        p.hp = derive(p).max_hp
    return gained


def roll_strike(p: Player, up: int, allow_crit: bool = True, combo: int = 0) -> tuple[int, bool]:
    st = derive(p)
    base = weapon_damage(p.weapon, up) * st.dmg_mult * (1 + COMBO_BONUS * max(0, min(combo, COMBO_MAX)))
    dmg = int(base * rng.uniform(*STRIKE_VARIANCE))
    crit = allow_crit and rng.random() < st.crit_chance
    if crit:
        dmg = int(dmg * st.crit_mult)
    return max(1, dmg), crit


# -------------------------------------------------------------- data access
async def _load_player(tx: Tx, uid: int) -> Player | None:
    row = await tx.fetchone("SELECT * FROM players WHERE user_id = ?", (uid,))
    return Player.from_row(row) if row else None


async def _load_battle(tx: Tx, uid: int) -> Battle | None:
    row = await tx.fetchone("SELECT * FROM battles WHERE user_id = ?", (uid,))
    return Battle.from_row(row) if row else None


async def _weapons(tx: Tx, uid: int) -> dict[str, int]:
    rows = await tx.fetchall("SELECT key, up FROM weapons WHERE user_id = ?", (uid,))
    owned = {r["key"]: r["up"] for r in rows}
    owned.setdefault("knife", 0)
    return owned


async def _pets(tx: Tx, uid: int) -> dict[int, int]:
    rows = await tx.fetchall("SELECT char_id, active FROM pets WHERE user_id = ?", (uid,))
    return {r["char_id"]: r["active"] for r in rows}


async def _kills(tx: Tx, uid: int) -> dict[int, int]:
    rows = await tx.fetchall("SELECT boss_id, count FROM boss_kills WHERE user_id = ?", (uid,))
    return {r["boss_id"]: r["count"] for r in rows}


async def _bump(tx: Tx, uid: int, key: str, amount: int = 1) -> None:
    if amount <= 0:
        return
    await tx.execute(
        "INSERT INTO tasks (user_id, day, key, progress) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, day, key) DO UPDATE SET progress = progress + excluded.progress",
        (uid, today_key(), key, amount),
    )


@dataclass
class View:
    player: Player
    battle: Battle | None
    stats: Stats
    weapons: dict[str, int]
    pets: dict[int, int]
    kills: dict[int, int]

    @property
    def pet_owned(self) -> bool:
        return self.player.char_id in self.pets

    @property
    def pet_active(self) -> bool:
        return bool(self.pets.get(self.player.char_id, 0))

    @property
    def weapon_up(self) -> int:
        return self.weapons.get(self.player.weapon, 0)

    @property
    def weapon_dmg(self) -> int:
        return int(weapon_damage(self.player.weapon, self.weapon_up) * self.stats.dmg_mult)


async def _view(tx: Tx, p: Player, b: Battle | None) -> View:
    return View(p, b, derive(p), await _weapons(tx, p.user_id), await _pets(tx, p.user_id), await _kills(tx, p.user_id))


@dataclass
class Result:
    ok: bool
    msg: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class Outcome:
    status: str = "ok"  # ok | error | stale | victory | death
    error: str = ""
    action: str = ""
    boss: Boss | None = None
    view: View | None = None
    dmg: int = 0
    crit: bool = False
    counter: int = 0
    absorbed: int = 0
    dodged: bool = False
    stunned: bool = False
    self_dmg: int = 0
    phase: int = 0
    phase_up: bool = False
    cost: int = 0
    amount: int = 0
    xp_gain: int = 0
    levelups: int = 0
    reward_coins: int = 0
    reward_xp: int = 0
    reward_gold: int = 0
    first_kill: bool = False
    unlocked_new: int = 0
    game_complete: bool = False
    penalty: int = 0
    combo: int = 0
    combo_broke: bool = False


# ------------------------------------------------------------------ players
async def ensure_player(uid: int, name: str, username: str | None) -> tuple[Player, bool]:
    name = (name or "").strip()[:64] or "ناشناس"
    username = (username or "")[:64]
    now = now_ts()
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            await tx.execute("INSERT INTO players (user_id) VALUES (?)", (uid,))
            p = Player(
                user_id=uid, name=name, username=username,
                coins=START_COINS, gold=START_GOLD,
                hp=max_hp(1), shield=BASE_SHIELD // 2,
                created_at=now, last_seen=now,
            )
            await p.save(tx)
            await tx.execute("INSERT OR IGNORE INTO weapons (user_id, key, up) VALUES (?, 'knife', 0)", (uid,))
            return p, True
        if name != p.name or username != p.username or now - p.last_seen > 120:
            p.name, p.username, p.last_seen = name, username, now
            await p.save(tx)
        return p, False


async def get_view(uid: int) -> View | None:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return None
        b = await _load_battle(tx, uid)
        return await _view(tx, p, b)


async def select_character(uid: int, char_id: int) -> Result:
    if char_id not in CHARACTERS:
        return Result(False, "کاراکتر نامعتبر است.")
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Result(False, "ابتدا /start را بزن.")
        p.char_id = char_id
        st = derive(p)
        p.hp = min(p.hp, st.max_hp)
        p.shield = min(p.shield, st.max_shield)
        await p.save(tx)
        await tx.execute("UPDATE battles SET pending = 0 WHERE user_id = ?", (uid,))
        return Result(True)


# ------------------------------------------------------------------ battle
async def enter_battle(uid: int, boss_id: int) -> Outcome:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Outcome(status="error", error="ابتدا /start را بزن.")
        boss = BOSSES.get(boss_id)
        if boss is None:
            return Outcome(status="error", error="این دروازه وجود ندارد.")
        if boss_id > p.unlocked:
            return Outcome(status="error", error="این دروازه هنوز بسته است. اول دروازه‌ی قبلی را بگشا!")
        b = await _load_battle(tx, uid)
        replaced = False
        if b is not None and b.boss_id != boss_id:
            await tx.execute("DELETE FROM battles WHERE user_id = ?", (uid,))
            b, replaced = None, True
        if b is None:
            b = Battle(user_id=uid, boss_id=boss_id, boss_hp=boss.hp, round=1, started_at=now_ts())
            await tx.execute("INSERT INTO battles (user_id) VALUES (?)", (uid,))
        st = derive(p)
        if p.hp > st.max_hp or p.shield > st.max_shield:
            p.hp, p.shield = min(p.hp, st.max_hp), min(p.shield, st.max_shield)
            await p.save(tx)
        if b.pending <= 0:
            weapons = await _weapons(tx, uid)
            b.pending, crit = roll_strike(p, weapons.get(p.weapon, 0), combo=b.combo)
            b.pending_crit = int(crit)
        await b.save(tx)
        out = Outcome(action="enter", boss=boss, view=await _view(tx, p, b))
        out.amount = int(replaced)
        return out


async def act(uid: int, action: str, token: int = 0) -> Outcome:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Outcome(status="error", error="ابتدا /start را بزن.")
        b = await _load_battle(tx, uid)
        if b is None:
            return Outcome(status="error", error="نبرد فعالی نداری. از منوی داستانی «شروع» را بزن.")
        boss = BOSSES[b.boss_id]
        st = derive(p)
        p.hp, p.shield = min(p.hp, st.max_hp), min(p.shield, st.max_shield)
        weapons = await _weapons(tx, uid)
        out = Outcome(action=action, boss=boss)

        def fail(msg: str) -> Outcome:
            out.status, out.error = "error", msg
            return out

        # ---------------------------------------------------- purchases
        if action in ("heal", "shield"):
            if action == "heal":
                if p.hp >= st.max_hp:
                    return await _finish_noop(tx, p, b, out, fail, "خونت از قبل پره!")
                if p.coins < HEAL_COST:
                    return await _finish_noop(tx, p, b, out, fail, f"سکه کافی نداری! (قیمت معجون: {HEAL_COST:,})")
                p.coins -= HEAL_COST
                out.amount = st.max_hp - p.hp
                p.hp = st.max_hp
                out.cost = HEAL_COST
                await _bump(tx, uid, "heal")
            else:
                if p.shield >= st.max_shield:
                    return await _finish_noop(tx, p, b, out, fail, "سپرت از قبل پره!")
                if p.coins < SHIELD_COST:
                    return await _finish_noop(tx, p, b, out, fail, f"سکه کافی نداری! (قیمت سپر: {SHIELD_COST:,})")
                p.coins -= SHIELD_COST
                out.amount = st.max_shield - p.shield
                p.shield = st.max_shield
                out.cost = SHIELD_COST
                await _bump(tx, uid, "shield")
            await p.save(tx)
            out.view = await _view(tx, p, b)
            return out

        if action not in ("hit", "pet", "power"):
            return fail("اکشن نامعتبر است.")

        # ---------------------------------------------------- attacks
        dmg, crit = 0, False
        if action == "hit":
            if b.pending <= 0:
                b.pending, c = roll_strike(p, weapons.get(p.weapon, 0), combo=b.combo)
                b.pending_crit = int(c)
            dmg, crit = b.pending, bool(b.pending_crit)
        elif action == "pet":
            pets = await _pets(tx, uid)
            if p.char_id not in pets:
                return await _finish_noop(tx, p, b, out, fail, "هنوز حیوان نبرد نخریده‌ای! از منوی «حیوانات نبرد» بخرش.")
            if not pets[p.char_id]:
                return await _finish_noop(tx, p, b, out, fail, "حیوانت برای نبرد غیرفعال است. از منوی «حیوانات نبرد» فعالش کن.")
            if b.pet_cd > 0:
                return await _finish_noop(tx, p, b, out, fail, f"حیوانت هنوز خسته است! {b.pet_cd} حرکت دیگر صبر کن.")
            dmg = int(rng.randint(*PET_DMG) * (1 + PET_LEVEL_BONUS * (p.level - 1)))
        else:  # power
            if b.power_cd > 0:
                return await _finish_noop(tx, p, b, out, fail, f"هنوز نیرو نگرفته‌ای! {b.power_cd} حرکت دیگر صبر کن.")
            base, _ = roll_strike(p, weapons.get(p.weapon, 0), allow_crit=False)
            dmg = int(base * POWER_MULT)
            out.self_dmg = max(1, int(st.max_hp * rng.uniform(*POWER_SELF_PCT)))
            p.hp = max(1, p.hp - out.self_dmg)

        out.dmg, out.crit = dmg, crit
        before = b.boss_hp
        dealt = min(dmg, b.boss_hp)
        b.boss_hp -= dealt
        p.damage_total += dealt
        await _bump(tx, uid, "damage", dealt)
        if action == "pet":
            p.pet_uses += 1
            out.xp_gain = PET_XP
        else:
            p.strikes += 1
            out.xp_gain = rng.randint(*STRIKE_XP)
            await _bump(tx, uid, "hits")
            if crit:
                p.crits += 1
                await _bump(tx, uid, "crit")

        # ---------------------------------------------------- victory
        if b.boss_hp <= 0:
            return await _victory(tx, p, b, boss, out, weapons)

        out.phase = phase_of(b.boss_hp, boss.hp)
        out.phase_up = out.phase > phase_of(before, boss.hp)
        out.levelups = apply_xp(p, out.xp_gain)
        if out.levelups:
            st = derive(p)

        # ---------------------------------------------------- boss counter
        if action == "pet":
            out.stunned = True
        elif st.dodge and rng.random() < st.dodge:
            out.dodged = True
        else:
            out.counter = int(rng.randint(boss.dmg_min, boss.dmg_max) * PHASE_MULT[out.phase])
            out.absorbed = min(p.shield, out.counter)
            p.shield -= out.absorbed
            p.hp -= out.counter - out.absorbed

        if action == "hit":
            b.combo = min(COMBO_MAX, b.combo + 1)
        if out.counter - out.absorbed > 0:
            out.combo_broke = b.combo >= 2
            b.combo = 0
        out.combo = b.combo

        # ---------------------------------------------------- death
        if p.hp <= 0:
            out.status = "death"
            out.penalty = min(p.coins, DEATH_PENALTY)
            p.coins -= out.penalty
            p.deaths += 1
            p.hp = derive(p).max_hp
            p.shield = 0
            await p.save(tx)
            await tx.execute("DELETE FROM battles WHERE user_id = ?", (uid,))
            out.view = await _view(tx, p, None)
            return out

        # ---------------------------------------------------- next round
        b.pet_cd = PET_COOLDOWN if action == "pet" else max(0, b.pet_cd - 1)
        b.power_cd = POWER_COOLDOWN if action == "power" else max(0, b.power_cd - 1)
        b.round += 1
        if action == "hit":
            b.pending, c = roll_strike(p, weapons.get(p.weapon, 0), combo=b.combo)
            b.pending_crit = int(c)
        await p.save(tx)
        await b.save(tx)
        out.view = await _view(tx, p, b)
        return out


async def _finish_noop(tx: Tx, p: Player, b: Battle, out: Outcome, fail, msg: str) -> Outcome:
    out.view = await _view(tx, p, b)
    return fail(msg)


async def _victory(tx: Tx, p: Player, b: Battle, boss: Boss, out: Outcome, weapons: dict[str, int]) -> Outcome:
    uid = p.user_id
    kills = await _kills(tx, uid)
    first = kills.get(boss.id, 0) == 0
    out.status, out.first_kill = "victory", first
    out.reward_coins = boss.coins if first else int(boss.coins * REPEAT_COIN_PCT)
    out.reward_xp = boss.xp if first else int(boss.xp * REPEAT_XP_PCT)
    out.reward_gold = boss.gold if first else 0
    p.coins += out.reward_coins
    p.gold += out.reward_gold
    out.levelups = apply_xp(p, out.xp_gain + out.reward_xp)
    p.kills += 1
    if first and boss.id == p.unlocked:
        if boss.id < LAST_BOSS:
            p.unlocked += 1
            out.unlocked_new = p.unlocked
        else:
            out.game_complete = True
    elif first and boss.id == LAST_BOSS:
        out.game_complete = True
    await tx.execute(
        "INSERT INTO boss_kills (user_id, boss_id, count) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, boss_id) DO UPDATE SET count = count + 1",
        (uid, boss.id),
    )
    await _bump(tx, uid, "kill")
    await p.save(tx)
    await tx.execute("DELETE FROM battles WHERE user_id = ?", (uid,))
    out.view = await _view(tx, p, None)
    return out


# ------------------------------------------------------------------ weapons
async def buy_weapon(uid: int, key: str) -> Result:
    w = WEAPONS.get(key)
    if w is None:
        return Result(False, "سلاح نامعتبر است.")
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Result(False, "ابتدا /start را بزن.")
        owned = await _weapons(tx, uid)
        if key in owned:
            return Result(False, "این سلاح را قبلاً داری!")
        if p.coins < w.price_coins:
            return Result(False, f"سکه کافی نداری! (نیاز: {w.price_coins:,})")
        if p.gold < w.price_gold:
            return Result(False, f"طلای کافی نداری! (نیاز: {w.price_gold})")
        p.coins -= w.price_coins
        p.gold -= w.price_gold
        p.weapon = key
        await tx.execute("INSERT OR IGNORE INTO weapons (user_id, key, up) VALUES (?, ?, 0)", (uid, key))
        await p.save(tx)
        await tx.execute("UPDATE battles SET pending = 0 WHERE user_id = ?", (uid,))
        return Result(True, f"{w.name} خریداری و تجهیز شد!")


async def upgrade_weapon(uid: int, key: str) -> Result:
    if key not in WEAPONS:
        return Result(False, "سلاح نامعتبر است.")
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Result(False, "ابتدا /start را بزن.")
        owned = await _weapons(tx, uid)
        if key not in owned:
            return Result(False, "اول باید این سلاح را بخری!")
        up = owned[key]
        if up >= WEAPON_UP_MAX:
            return Result(False, "این سلاح به حداکثر ارتقا رسیده است!")
        cost = upgrade_cost(key, up)
        if p.coins < cost:
            return Result(False, f"سکه کافی نداری! (نیاز: {cost:,})")
        p.coins -= cost
        await p.save(tx)
        await tx.execute("UPDATE weapons SET up = up + 1 WHERE user_id = ? AND key = ?", (uid, key))
        await tx.execute("UPDATE battles SET pending = 0 WHERE user_id = ?", (uid,))
        return Result(True, f"{WEAPONS[key].name} به +{up + 1} ارتقا یافت!", {"up": up + 1, "cost": cost})


async def equip_weapon(uid: int, key: str) -> Result:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Result(False, "ابتدا /start را بزن.")
        owned = await _weapons(tx, uid)
        if key not in owned:
            return Result(False, "این سلاح را نداری!")
        if p.weapon == key:
            return Result(False, "این سلاح همین الان در دستت است.")
        p.weapon = key
        await p.save(tx)
        await tx.execute("UPDATE battles SET pending = 0 WHERE user_id = ?", (uid,))
        return Result(True, f"{WEAPONS[key].name} را برداشتی!")


# --------------------------------------------------------------------- pets
async def grant_pet(uid: int, char_id: int) -> bool:
    if char_id not in CHARACTERS:
        return False
    async with db.tx() as tx:
        if await _load_player(tx, uid) is None:
            return False
        await tx.execute("INSERT OR IGNORE INTO pets (user_id, char_id, active) VALUES (?, ?, 1)", (uid, char_id))
        return True


async def toggle_pet(uid: int, char_id: int) -> Result:
    async with db.tx() as tx:
        pets = await _pets(tx, uid)
        if char_id not in pets:
            return Result(False, "این حیوان را نداری!")
        new = 0 if pets[char_id] else 1
        await tx.execute("UPDATE pets SET active = ? WHERE user_id = ? AND char_id = ?", (new, uid, char_id))
        return Result(True, "حیوانت برای نبرد فعال شد!" if new else "حیوانت از نبرد کنار رفت.", {"active": new})


async def create_pet_order(uid: int, char_id: int, phone: str) -> Result:
    if char_id not in CHARACTERS:
        return Result(False, "کاراکتر نامعتبر است.")
    async with db.tx() as tx:
        if char_id in await _pets(tx, uid):
            return Result(False, "این حیوان را قبلاً داری!")
        if await tx.fetchone("SELECT 1 FROM pet_orders WHERE user_id = ? AND char_id = ? AND status = 'pending'", (uid, char_id)):
            return Result(False, "رسید قبلی تو هنوز در انتظار بررسی است.")
        oid = await tx.insert(
            "INSERT INTO pet_orders (user_id, char_id, phone, created_at) VALUES (?, ?, ?, ?)",
            (uid, char_id, phone, now_ts()),
        )
        return Result(True, "", {"order_id": oid})


async def pet_order_blocker(uid: int, char_id: int) -> str:
    """Returns a user-facing reason why a purchase cannot start, or an empty string."""
    async with db.tx() as tx:
        if char_id not in CHARACTERS:
            return "کاراکتر نامعتبر است."
        if char_id in await _pets(tx, uid):
            return "این حیوان را قبلاً داری!"
        if await tx.fetchone("SELECT 1 FROM pet_orders WHERE user_id = ? AND char_id = ? AND status = 'pending'", (uid, char_id)):
            return "رسید قبلی تو هنوز در انتظار بررسی است."
        return ""


async def decide_pet_order(order_id: int, admin_id: int, approve: bool) -> Result:
    async with db.tx() as tx:
        row = await tx.fetchone("SELECT * FROM pet_orders WHERE id = ?", (order_id,))
        if row is None:
            return Result(False, "این سفارش پیدا نشد.")
        if row["status"] != "pending":
            return Result(False, "این رسید قبلاً بررسی شده است.")
        status = "approved" if approve else "rejected"
        await tx.execute("UPDATE pet_orders SET status = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                         (status, now_ts(), admin_id, order_id))
        if approve:
            await tx.execute("INSERT OR IGNORE INTO pets (user_id, char_id, active) VALUES (?, ?, 1)", (row["user_id"], row["char_id"]))
        return Result(True, "", {"user_id": row["user_id"], "char_id": row["char_id"]})


# -------------------------------------------------------------------- daily
async def daily_status(uid: int) -> dict:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return {"ready": False, "streak": 0, "wait": 0, "next_streak": 1}
        today = today_key()
        ready = p.last_daily != today
        streak = p.streak if p.last_daily in (today, yesterday_key()) else 0
        return {
            "ready": ready,
            "streak": streak,
            "next_streak": (streak + 1) if ready else streak,
            "wait": 0 if ready else seconds_to_midnight(),
        }


async def claim_daily(uid: int) -> Result:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Result(False, "ابتدا /start را بزن.")
        today = today_key()
        if p.last_daily == today:
            return Result(False, "جایزه‌ی امروز را قبلاً گرفته‌ای! فردا برگرد.")
        streak = p.streak + 1 if p.last_daily == yesterday_key() else 1
        mult = 1 + DAILY_STREAK_BONUS * min(streak - 1, DAILY_STREAK_CAP)
        coins = int(rng.randint(*DAILY_COINS) * mult)
        xp = rng.randint(*DAILY_XP)
        gold = 1 if streak % DAILY_GOLD_EVERY == 0 else 0
        p.coins += coins
        p.gold += gold
        p.last_daily, p.streak = today, streak
        levels = apply_xp(p, xp)
        await p.save(tx)
        return Result(True, "", {"coins": coins, "xp": xp, "gold": gold, "streak": streak, "levels": levels})


# -------------------------------------------------------------------- tasks
async def get_tasks(uid: int) -> list[dict]:
    async with db.tx() as tx:
        rows = await tx.fetchall("SELECT key, progress, claimed FROM tasks WHERE user_id = ? AND day = ?", (uid, today_key()))
        state = {r["key"]: (r["progress"], r["claimed"]) for r in rows}
    out = []
    for task in TASKS:
        progress, claimed = state.get(task.key, (0, 0))
        out.append({"task": task, "progress": min(progress, task.target), "claimed": bool(claimed), "done": progress >= task.target})
    return out


async def claim_task(uid: int, key: str) -> Result:
    task = TASKS_BY_KEY.get(key)
    if task is None:
        return Result(False, "تسک نامعتبر است.")
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Result(False, "ابتدا /start را بزن.")
        row = await tx.fetchone("SELECT progress, claimed FROM tasks WHERE user_id = ? AND day = ? AND key = ?", (uid, today_key(), key))
        if row is None or row["progress"] < task.target:
            return Result(False, "این تسک هنوز کامل نشده است!")
        if row["claimed"]:
            return Result(False, "جایزه‌ی این تسک را قبلاً گرفته‌ای!")
        await tx.execute("UPDATE tasks SET claimed = 1 WHERE user_id = ? AND day = ? AND key = ?", (uid, today_key(), key))
        p.coins += task.coins
        p.gold += task.gold
        levels = apply_xp(p, task.xp)
        await p.save(tx)
        return Result(True, "", {"coins": task.coins, "xp": task.xp, "gold": task.gold, "levels": levels})


# ----------------------------------------------------------------- referral
async def apply_referral(new_uid: int, inviter_uid: int) -> bool:
    if new_uid == inviter_uid:
        return False
    async with db.tx() as tx:
        me = await _load_player(tx, new_uid)
        inviter = await _load_player(tx, inviter_uid)
        if me is None or inviter is None or me.referred_by:
            return False
        me.referred_by = inviter_uid
        me.coins += REFERRAL_INVITEE_COINS
        inviter.coins += REFERRAL_INVITER_COINS
        inviter.ref_count += 1
        apply_xp(inviter, REFERRAL_INVITER_XP)
        await me.save(tx)
        await inviter.save(tx)
        return True


# -------------------------------------------------------------------- social
async def leaderboard(limit: int = 10) -> list[Player]:
    async with db.tx() as tx:
        rows = await tx.fetchall(
            "SELECT * FROM players ORDER BY unlocked DESC, level DESC, xp DESC, kills DESC LIMIT ?", (limit,)
        )
        return [Player.from_row(r) for r in rows]


async def rank_of(uid: int) -> tuple[int, int]:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        total = (await tx.fetchone("SELECT COUNT(*) AS n FROM players"))["n"]
        if p is None:
            return 0, total
        better = (await tx.fetchone(
            "SELECT COUNT(*) AS n FROM players WHERE unlocked > ? OR (unlocked = ? AND level > ?) "
            "OR (unlocked = ? AND level = ? AND xp > ?)",
            (p.unlocked, p.unlocked, p.level, p.unlocked, p.level, p.xp),
        ))["n"]
        return better + 1, total


# -------------------------------------------------------------------- admin
async def admin_stats() -> dict:
    async with db.tx() as tx:
        row = await tx.fetchone(
            "SELECT COUNT(*) AS n, COALESCE(SUM(kills),0) AS kills, COALESCE(SUM(deaths),0) AS deaths, "
            "COALESCE(SUM(coins),0) AS coins FROM players"
        )
        active = (await tx.fetchone("SELECT COUNT(*) AS n FROM players WHERE last_seen > ?", (now_ts() - 86400,)))["n"]
        fighting = (await tx.fetchone("SELECT COUNT(*) AS n FROM battles"))["n"]
        pets = (await tx.fetchone("SELECT COUNT(*) AS n FROM pets"))["n"]
        return {"players": row["n"], "kills": row["kills"], "deaths": row["deaths"], "coins": row["coins"],
                "active": active, "fighting": fighting, "pets": pets}


async def admin_grant(uid: int, coins: int = 0, gold: int = 0, xp: int = 0) -> Result:
    async with db.tx() as tx:
        p = await _load_player(tx, uid)
        if p is None:
            return Result(False, "این کاربر هنوز بازی را شروع نکرده است.")
        p.coins = max(0, p.coins + coins)
        p.gold = max(0, p.gold + gold)
        if xp > 0:
            apply_xp(p, xp)
        await p.save(tx)
        return Result(True, "", {"player": p})


async def admin_reset(uid: int) -> Result:
    async with db.tx() as tx:
        if await _load_player(tx, uid) is None:
            return Result(False, "این کاربر هنوز بازی را شروع نکرده است.")
        for table in ("weapons", "pets", "boss_kills", "battles", "tasks"):
            await tx.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
        p = Player(user_id=uid, coins=START_COINS, gold=START_GOLD, hp=max_hp(1), shield=BASE_SHIELD // 2, created_at=now_ts(), last_seen=now_ts())
        old = await tx.fetchone("SELECT name, username FROM players WHERE user_id = ?", (uid,))
        p.name, p.username = old["name"], old["username"]
        await p.save(tx)
        await tx.execute("INSERT OR IGNORE INTO weapons (user_id, key, up) VALUES (?, 'knife', 0)", (uid,))
        return Result(True)
