# support_bot/support_bot.py
import os
import asyncio
import logging
import html
import contextlib
import time
import asyncpg
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BotCommand,
    BotCommandScopeDefault,
    MenuButtonCommands,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, StateFilter

logging.basicConfig(level=logging.INFO)

# .env рядом с этим файлом (support_bot/.env)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN")
SUPPORT_GROUP_ID_RAW = os.getenv("SUPPORT_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("❌ SUPPORT_BOT_TOKEN не задан в .env (support_bot)")
if not SUPPORT_GROUP_ID_RAW:
    raise RuntimeError("❌ SUPPORT_CHAT_ID не задан в .env (support_bot)")

SUPPORT_GROUP_ID = int(SUPPORT_GROUP_ID_RAW)
SUPPORT_DB_DSN = os.getenv("SUPPORT_DB_DSN")

# ✅ важно: timeout числом, parse_mode через DefaultBotProperties
session = AiohttpSession(timeout=30)
bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

_db_pool = None

# --- Храним последнее обращение пользователя (в памяти) ---
user_last_question: dict[int, dict[str, str]] = {}

# ЧТ support-бота: текущая поверхность пользователя.
support_surface: dict[int, str] = {}
support_hint_ts: dict[int, int] = {}
support_cleanup_ids: dict[int, set[int]] = {}

# Кнопки для поддерживаемых тем
BUTTONS = [
    ("Проблемы с публикацией/размещением объявления", "publish_problem"),
    ("Проблемы с поиском и фильтрами (soon)", "search_filters_problem"),
    ("Вопрос по работе с личными сообщениями", "dm_question"),
    ("Ошибка в получении уведомлений", "notification_error"),
    ("Вопрос по управлению профилем (soon)", "profile_question_soon"),
    ("Проблемы отображения/поиска моих объявлений", "myads_problem"),
    ("Ошибка или баг в работе бота", "bot_error"),
    ("Вопросы по функциям сервиса", "service_feature_question"),
    ("Хочу предложить новую функцию", "suggest_feature"),
    ("Другое", "other"),
]

SOON_CALLBACKS = {"search_filters_problem", "profile_question_soon"}

# callback_data для меню
CB_MENU_START = "sb_menu_start"
CB_BACK_MENU = "support:back_menu"


async def _track_cleanup_message(user_id: int, message: Message | None) -> None:
    if not message:
        return
    support_cleanup_ids.setdefault(int(user_id), set()).add(int(message.message_id))


async def _cleanup_user_messages(chat_id: int, user_id: int, *, exclude_ids: set[int] | None = None) -> None:
    exclude_ids = exclude_ids or set()
    ids = list(support_cleanup_ids.pop(int(user_id), set()))
    keep: set[int] = set()

    for mid in ids:
        if int(mid) in exclude_ids:
            keep.add(int(mid))
            continue
        with contextlib.suppress(Exception):
            await bot.delete_message(chat_id=int(chat_id), message_id=int(mid))

    if keep:
        support_cleanup_ids[int(user_id)] = keep


async def _delete_later(message: Message, seconds: int = 3) -> None:
    await asyncio.sleep(seconds)
    with contextlib.suppress(Exception):
        await message.delete()


async def _temp_hint(message: Message, text: str, seconds: int = 3) -> None:
    sent = await message.answer(text)
    asyncio.create_task(_delete_later(sent, seconds=seconds))


def _support_trash_hint(user_id: int) -> str:
    surface = support_surface.get(int(user_id), "menu")

    if surface == "start":
        return "Используй кнопки выше: выбери тему обращения или открой /menu."

    if surface == "categories":
        return "Используй кнопки выше: создай обращение или перейди в /menu."

    if surface == "my_tickets":
        return "Используй кнопки выше или перейди в /menu."

    return "Используй кнопки выше: создай обращение, посмотри свои обращения или открой нужный раздел."


def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(text=text, callback_data=cb)] for (text, cb) in BUTTONS]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


TICKETS_PAGE_SIZE = 5


def _ticket_status_label(status: str) -> str:
    return "✅ закрыто" if str(status or "").lower() == "closed" else "🟢 открыто"


def _short_text(text: str, limit: int = 140) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _fmt_msk(dt) -> str:
    try:
        from datetime import timedelta
        return (dt + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def get_my_tickets_keyboard(ticket_rows, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    rows = []

    for r in ticket_rows:
        rows.append([
            InlineKeyboardButton(
                text=f"🎫 Открыть #{r['id']}",
                callback_data=f"support:ticket:{r['id']}:{page}",
            )
        ])

    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton(text="⬅️ Предыдущие", callback_data=f"support:my_tickets:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="Следующие ➡️", callback_data=f"support:my_tickets:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def fetch_user_tickets_page(user_id: int, page: int) -> tuple[list, bool, bool]:
    if not _db_pool:
        return [], False, False

    page = max(int(page), 0)
    limit = TICKETS_PAGE_SIZE + 1
    offset = page * TICKETS_PAGE_SIZE

    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, topic_title, description, status, created_at, last_answer
            FROM support_tickets
            WHERE user_id = $1
              AND created_at >= now() - interval '90 days'
            ORDER BY created_at DESC, id DESC
            LIMIT $2 OFFSET $3
            """,
            int(user_id),
            int(limit),
            int(offset),
        )

    has_next = len(rows) > TICKETS_PAGE_SIZE
    visible = list(rows[:TICKETS_PAGE_SIZE])
    has_prev = page > 0

    return visible, has_prev, has_next


def render_my_tickets(rows, page: int) -> str:
    if not rows:
        return (
            "📂 <b>Мои обращения</b>\n\n"
            "За последние 90 дней обращений не найдено.\n\n"
            "Создай обращение через кнопку «📝 Создать обращение»."
        )

    lines = [
        "📂 <b>Мои обращения</b>",
        "",
        "Показываются обращения за последние 90 дней.",
        f"Страница: {int(page) + 1}",
        "",
    ]

    for r in rows:
        created = _fmt_msk(r["created_at"])
        topic = html.escape(str(r["topic_title"] or "Без темы"))
        desc = html.escape(_short_text(r["description"] or "", 160))
        answer = html.escape(_short_text(r["last_answer"] or "", 180))

        lines.append(f"🎫 <b>#{r['id']}</b> — {_ticket_status_label(r['status'])}")
        lines.append(f"Тема: {topic}")
        lines.append(f"Создано: {created} МСК")
        if desc:
            lines.append(f"Текст: {desc}")
        if answer:
            lines.append(f"Ответ: {answer}")
        lines.append("")

    return "\n".join(lines).rstrip()


def get_categories_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(text=text, callback_data=cb)] for (text, cb) in BUTTONS]
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_menu_keyboard() -> InlineKeyboardMarkup:
    bot_username = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
    channel_username = (os.getenv("CHANNEL_USERNAME") or "").strip().lstrip("@")

    bot_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me"
    channel_url = f"https://t.me/{channel_username}" if channel_username else "https://t.me"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Создать обращение", callback_data=CB_MENU_START)],
            [InlineKeyboardButton(text="📂 Мои обращения", callback_data="support:my_tickets:0")],
            [InlineKeyboardButton(text="🤖 Открыть основной бот", url=bot_url)],
            [InlineKeyboardButton(text="📣 Канал объявлений", url=channel_url)],
        ]
    )


def is_support_group(event_chat_id: int | None) -> bool:
    return bool(event_chat_id) and int(event_chat_id) == SUPPORT_GROUP_ID


class SupportStates(StatesGroup):
    waiting_text = State()
    suggest_feature = State()
    reply_mode = State()  # саппорт пишет ответ пользователю


async def show_start(message: Message, state: FSMContext) -> None:
    """
    Единая функция: показывает стартовый экран саппорта
    """
    await state.clear()
    if message.from_user:
        support_surface[int(message.from_user.id)] = "categories"

    await message.answer(
        "👋 <b>Это официальный саппорт FindexHub</b>\n"
        "Все обращения обрабатываются через форму.\n"
        "Менеджер свяжется с вами при необходимости.\n\n"
        "Нажми кнопку ниже, чтобы создать обращение.",
        reply_markup=get_categories_keyboard(),
    )


# -------------------------
# ✅ STARTUP: ставим меню-кнопку слева от ввода + команды
# -------------------------
async def on_startup(dispatcher: Dispatcher) -> None:
    global _db_pool
    if SUPPORT_DB_DSN:
        _db_pool = await asyncpg.create_pool(SUPPORT_DB_DSN)
        logging.info("✅ support db connected")
    # 1) команды (чтобы Telegram красиво показывал подсказки)
    try:
        await bot.set_my_commands(
            commands=[
                BotCommand(command="start", description="Старт"),
                BotCommand(command="menu", description="Меню"),
            ],
            scope=BotCommandScopeDefault(),
        )
    except Exception as e:
        logging.exception("Не удалось set_my_commands: %r", e)

    # 2) кнопка меню слева от строки ввода (Bot Menu Button)
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logging.info("✅ Support bot: Menu Button установлен (MenuButtonCommands)")
    except Exception as e:
        logging.exception("Не удалось set_chat_menu_button: %r", e)


# ✅ Регистрируем startup ПРАВИЛЬНО (без lambda и без вызова on_startup())
dp.startup.register(on_startup)


# -------------------------
# ✅ /start
# -------------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    with contextlib.suppress(Exception):
        await message.delete()
    await show_start(message, state)


# -------------------------
# ✅ /menu (то, что ты называешь "главное меню саппорт-бота")
# -------------------------
@dp.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user:
        support_surface[int(message.from_user.id)] = "menu"
        await _cleanup_user_messages(message.chat.id, message.from_user.id)

    with contextlib.suppress(Exception):
        await message.delete()

    await message.answer(
        "👋 <b>FindexHub Support</b>\n\n"
        "Это официальный саппорт FindexHub.\n"
        "Все обращения обрабатываются через форму.\n"
        "Менеджер свяжется с тобой при необходимости.\n\n"
        "Выбери действие:",
        reply_markup=get_menu_keyboard(),
    )


# Кнопка "▶️ Start" из меню

async def fetch_ticket_detail(user_id: int, ticket_id: int):
    if not _db_pool:
        return None

    async with _db_pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT id, topic_title, description, status, created_at, last_answer
            FROM support_tickets
            WHERE id = $1
              AND user_id = $2
              AND created_at >= now() - interval '90 days'
            LIMIT 1
            """,
            int(ticket_id),
            int(user_id),
        )


def render_ticket_detail(r) -> str:
    if not r:
        return (
            "🎫 <b>Обращение не найдено</b>\n\n"
            "Возможно, оно старше 90 дней или недоступно."
        )

    created = _fmt_msk(r["created_at"])
    topic = html.escape(str(r["topic_title"] or "Без темы"))
    desc = html.escape(str(r["description"] or "").strip())
    answer = html.escape(str(r["last_answer"] or "").strip())

    lines = [
        f"🎫 <b>Обращение #{r['id']}</b> — {_ticket_status_label(r['status'])}",
        "",
        f"Тема: {topic}",
        f"Создано: {created} МСК",
        "",
        "📩 <b>Запрос:</b>",
        desc or "—",
    ]

    if answer:
        lines.extend(["", "💬 <b>Ответ поддержки:</b>", answer])

    return "\n".join(lines)


def get_ticket_detail_keyboard(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К списку", callback_data=f"support:my_tickets:{page}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=CB_BACK_MENU)],
        ]
    )


@dp.callback_query(F.data.regexp(r"^support:ticket:\d+:\d+$"))
async def cb_ticket_detail(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    support_surface[int(callback.from_user.id)] = "my_tickets"

    parts = str(callback.data or "").split(":")
    ticket_id = int(parts[2])
    page = int(parts[3])

    row = await fetch_ticket_detail(callback.from_user.id, ticket_id)

    if callback.message:
        await _cleanup_user_messages(
            callback.message.chat.id,
            callback.from_user.id,
            exclude_ids={int(callback.message.message_id)},
        )
        await callback.message.edit_text(
            render_ticket_detail(row),
            reply_markup=get_ticket_detail_keyboard(page),
        )



@dp.callback_query(F.data.regexp(r"^support:my_tickets(?::\d+)?$"))
async def cb_my_tickets(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    support_surface[int(callback.from_user.id)] = "my_tickets"

    parts = str(callback.data or "").split(":")
    try:
        page = int(parts[-1]) if len(parts) >= 3 else 0
    except Exception:
        page = 0

    rows, has_prev, has_next = await fetch_user_tickets_page(callback.from_user.id, page)

    if callback.message:
        await _cleanup_user_messages(
            callback.message.chat.id,
            callback.from_user.id,
            exclude_ids={int(callback.message.message_id)},
        )
        await callback.message.edit_text(
            render_my_tickets(rows, page),
            reply_markup=get_my_tickets_keyboard(rows, page, has_prev, has_next),
        )

@dp.callback_query(F.data == CB_BACK_MENU)
async def cb_back_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    support_surface[int(callback.from_user.id)] = "menu"

    if callback.message:
        await _cleanup_user_messages(
            callback.message.chat.id,
            callback.from_user.id,
            exclude_ids={int(callback.message.message_id)},
        )
        await callback.message.edit_text(
            "👋 <b>FindexHub Support</b>\n\n"
            "Это официальный саппорт FindexHub.\n"
            "Все обращения обрабатываются через форму.\n"
            "Менеджер свяжется с тобой при необходимости.\n\n"
            "Выбери действие:",
            reply_markup=get_menu_keyboard(),
        )

    await callback.answer()


@dp.callback_query(F.data == CB_MENU_START)
async def cb_menu_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    support_surface[int(callback.from_user.id)] = "categories"

    if callback.message:
        await callback.message.edit_text(
            "Выбери тему обращения:",
            reply_markup=get_categories_keyboard(),
        )

    await callback.answer()


@dp.message(StateFilter(None), F.chat.type == "private", F.text & ~F.text.startswith("/"))
async def support_start_menu_trash(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    surface = support_surface.get(int(user.id))
    if surface not in {"start", "menu", "categories", "my_tickets"}:
        return

    with contextlib.suppress(Exception):
        await message.delete()

    now_ts = int(time.time())
    last_ts = int(support_hint_ts.get(int(user.id)) or 0)
    if now_ts - last_ts < 3:
        return

    support_hint_ts[int(user.id)] = now_ts
    await _temp_hint(message, _support_trash_hint(int(user.id)), seconds=3)


# -------------------------
# остальная логика (без изменений)
# -------------------------
@dp.callback_query(F.data.in_(SOON_CALLBACKS))
async def soon_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Загрузка... Этот раздел пока в разработке.", show_alert=True)


@dp.callback_query(F.data == "suggest_feature")
async def feature_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Пожалуйста, опишите ваше предложение по 4 пунктам:\n"
        "1) Что добавить?\n"
        "2) Зачем это нужно?\n"
        "3) Кому это поможет?\n"
        "4) Пример использования.",
        reply_markup=None,
    )
    await _track_cleanup_message(callback.from_user.id, callback.message)
    await state.set_state(SupportStates.suggest_feature)
    await state.update_data(last_callback="suggest_feature")
    await callback.answer()


@dp.message(SupportStates.suggest_feature)
async def handle_suggest_feature(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    question = (message.text or "").strip()
    if not question:
        await message.answer("Напиши текст предложения одним сообщением 🙂")
        return

    await _track_cleanup_message(user.id, message)

    user_last_question[user.id] = {"theme": "Хочу предложить новую функцию", "text": question}

    ticket_id = await create_support_ticket(
        user.id,
        user.username,
        f"{user.first_name or ''} {user.last_name or ''}".strip(),
        "Хочу предложить новую функцию",
        question
    )

    await send_support_message_to_group(
        theme_text="Хочу предложить новую функцию",
        user=user,
        question_text=question,
        ticket_id=ticket_id,
    )

    sent = await message.answer(
        "Спасибо за вашу идею! Она передана команде разработки ✅",
        reply_markup=get_categories_keyboard(),
    )
    await _track_cleanup_message(user.id, sent)
    await state.clear()


@dp.callback_query(
    F.data.in_(
        {
            "publish_problem",
            "dm_question",
            "notification_error",
            "myads_problem",
            "bot_error",
            "service_feature_question",
            "other",
        }
    )
)
async def ask_for_problem_details(callback: types.CallbackQuery, state: FSMContext):
    selected_text = next((text for text, cb in BUTTONS if cb == callback.data), "Без темы")

    await state.set_state(SupportStates.waiting_text)
    await state.update_data(last_callback=callback.data)

    await callback.message.edit_text(
        f"Пожалуйста, опиши подробности по теме:\n<b>{selected_text}</b>\n\n"
        "Максимально подробно опиши проблему, вопрос или твой кейс.",
        reply_markup=None,
    )
    await _track_cleanup_message(callback.from_user.id, callback.message)
    await callback.answer()


@dp.message(SupportStates.waiting_text)
async def handle_problem_details(message: Message, state: FSMContext):
    user = message.from_user
    if not user:
        return

    question = (message.text or "").strip()
    if not question:
        await message.answer("Напиши текст обращения одним сообщением 🙂")
        return

    await _track_cleanup_message(user.id, message)

    data = await state.get_data()
    theme_callback = data.get("last_callback")
    theme_text = next((text for text, cb in BUTTONS if cb == theme_callback), "Без темы")

    user_last_question[user.id] = {"theme": theme_text, "text": question}

    ticket_id = await create_support_ticket(
        user.id,
        user.username,
        f"{user.first_name or ''} {user.last_name or ''}".strip(),
        theme_text,
        question
    )

    await send_support_message_to_group(theme_text, user, question, ticket_id=ticket_id)

    sent = await message.answer(
        f"✅ Обращение по теме <b>{theme_text}</b> отправлено в поддержку.\n"
        "Менеджер свяжется с тобой при необходимости.",
        reply_markup=get_categories_keyboard(),
    )
    await _track_cleanup_message(user.id, sent)
    await state.clear()



async def create_support_ticket(user_id, username, full_name, theme, text):
    if not _db_pool:
        return None

    async with _db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO support_tickets (
                user_id,
                user_username,
                user_full_name,
                topic_title,
                description,
                status
            )
            VALUES ($1, $2, $3, $4, $5, 'open')
            RETURNING id
            """,
            user_id,
            username,
            full_name,
            theme,
            text
        )
        return int(row["id"]) if row else None

async def send_support_message_to_group(theme_text: str, user: types.User, question_text: str, ticket_id: int | None = None):
    callback_data = f"support_reply_{int(ticket_id)}_{user.id}" if ticket_id else f"support_reply_0_{user.id}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Ответить", callback_data=callback_data)]
        ]
    )

    username = f"@{user.username}" if user.username else "[без username]"
    ticket_label = f" #{ticket_id}" if ticket_id else ""
    msg = (
        f"🆘 <b>[ОБРАЩЕНИЕ{ticket_label}]</b>\n"
        f"Тема: <b>{theme_text}</b>\n"
        f"От: {username} (id: <code>{user.id}</code>)\n\n"
        f"<b>Текст обращения:</b>\n{question_text}"
    )

    await bot.send_message(SUPPORT_GROUP_ID, msg, reply_markup=kb)


@dp.callback_query(F.data.regexp(r"^support_reply_(\d+)_(\d+)$"))
async def support_reply_callback(callback: CallbackQuery, state: FSMContext):
    chat_id = callback.message.chat.id if callback.message else None
    if not is_support_group(chat_id):
        await callback.answer("Недоступно.", show_alert=True)
        return

    parts = str(callback.data or "").split("_")
    ticket_id = int(parts[-2])
    user_id = int(parts[-1])

    theme = user_last_question.get(user_id, {}).get("theme", "")
    question = user_last_question.get(user_id, {}).get("text", "")

    await state.set_state(SupportStates.reply_mode)
    await state.update_data(
        reply_to=user_id,
        reply_ticket_id=ticket_id,
        reply_theme=theme,
        reply_question=question,
    )

    preview = question.strip()
    if len(preview) > 600:
        preview = preview[:600] + "…"

    await callback.message.reply(
        f"✉️ Отправь следующее сообщение — и я отправлю его пользователю <code>{user_id}</code> в личку.\n\n"
        f"<b>Заявка (цитата):</b>\n"
        f"Тема: <b>{theme}</b>\n"
        f"«{preview}»",
    )
    await callback.answer()


async def close_support_ticket(ticket_id: int | None, answer_text: str, actor_id: int | None = None):
    if not _db_pool or not ticket_id:
        return

    async with _db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE support_tickets
            SET status = 'closed',
                last_answer = $1,
                closed_at = now(),
                closed_by = $2
            WHERE id = $3
            """,
            answer_text,
            actor_id,
            int(ticket_id),
        )
        await conn.execute(
            """
            INSERT INTO support_ticket_events (ticket_id, event_type, actor_id, payload)
            VALUES ($1, 'support_answered', $2, jsonb_build_object('answer', $3))
            """,
            int(ticket_id),
            actor_id,
            answer_text,
        )


@dp.message(SupportStates.reply_mode)
async def support_send_answer_to_user(message: Message, state: FSMContext):
    if not is_support_group(message.chat.id):
        return

    data = await state.get_data()
    user_id = data.get("reply_to")
    ticket_id = data.get("reply_ticket_id")
    theme = data.get("reply_theme", "")
    question = data.get("reply_question", "")
    support_text = (message.text or "").strip()

    if not user_id:
        await message.reply("Не найден user_id для ответа. Нажми «Ответить» заново.")
        await state.clear()
        return

    if not support_text:
        await message.reply("Ответ пустой. Напиши текст одним сообщением.")
        return

    quote = question.strip()
    if len(quote) > 800:
        quote = quote[:800] + "…"

    out = (
        f"📝 <b>Твой запрос</b> (тема: <b>{theme}</b>):\n"
        f"«{quote}»\n\n"
        f"💬 <b>Ответ поддержки:</b>\n"
        f"{support_text}"
    )

    try:
        sent = await bot.send_message(user_id, out)
        await _track_cleanup_message(int(user_id), sent)
        await close_support_ticket(
            int(ticket_id) if ticket_id else None,
            support_text,
            int(message.from_user.id) if message.from_user else None,
        )
        await message.reply("✅ Ответ отправлен пользователю в ЛС.")
    except Exception as e:
        await message.reply(f"❌ Ошибка отправки пользователю: <code>{e}</code>")
    finally:
        await state.clear()


@dp.callback_query()
async def fallback_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Некорректная кнопка.", show_alert=True)


async def main():
    try:
        await dp.start_polling(bot)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
