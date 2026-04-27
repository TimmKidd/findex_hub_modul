# findex_bot/handlers/menu.py
from __future__ import annotations

import contextlib
import logging

from typing import Optional, Any
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext

import findex_bot.runtime as runtime
from findex_bot.utils.ui_surface import clear_surface, enter_surface

from findex_bot.db.db import get_sessionmaker
from findex_bot.db.daily_limits import get_count as db_get_pub_count
from findex_bot.db.repo import RespondRepo
from findex_bot.db.models import Respond
from findex_bot.utils.ui_utils import (
    utc_seconds_to_reset,
    format_hhmmss,
    DAILY_FREE_LIMIT,
    is_unlimited,
)

from findex_bot.handlers.start import show_roles
from findex_bot.utils.obs import log_event

router = Router()
logger = logging.getLogger(__name__)

CB_DIAG = "menu_diag"
CB_DIAG_BACK = "menu_diag_back"
CB_START = "menu_start"
CB_ALERTS = "alerts_open"
CB_REFRESH = "menu_refresh"
CB_DIAG_PENDING_OPEN = "diag_pending_open"

CB_RESPONDS_ROOT = "menu_responds"
CB_RESPONDS_ROLE = "menu_responds_role"
CB_RESPONDS_BUCKET = "menu_responds_bucket"
CB_RESPOND_OPEN_FROM_LIST = "respond_open_from_list"

ACTIVE_STATUSES = {"NEW", "INVITED", "IN_DIALOG"}
CLOSED_STATUSES = {"CLOSED_BY_OWNER", "CLOSED_BY_CANDIDATE", "CLOSED_SYSTEM"}

RESPONDS_PAGE_SIZE = 10

MENU_MSG_KEY = "menu:last:{user_id}"


def _diag_mod():
    from findex_bot.handlers import diagnostics as diag_mod  # type: ignore
    return diag_mod


def _menu_kb(channel_username: str) -> InlineKeyboardMarkup:
    channel_username = (channel_username or "").lstrip("@").strip()
    channel_url = f"https://t.me/{channel_username}" if channel_username else "https://t.me/"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📩 Мои отклики", callback_data=CB_RESPONDS_ROOT)],
        [InlineKeyboardButton(text="🔔 Мои уведомления", callback_data=CB_ALERTS)],
        [InlineKeyboardButton(text="🛠 Диагностика", callback_data=CB_DIAG)],
        [InlineKeyboardButton(text="🆘 Support", url="https://t.me/Findex_support_bot")],
        [InlineKeyboardButton(text="📣 Канал - обязательная подписка", url=channel_url)],
        [InlineKeyboardButton(text="▶️ Start", callback_data=CB_START)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _responds_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Я откликался", callback_data=f"{CB_RESPONDS_ROLE}:candidate")],
            [InlineKeyboardButton(text="🧑‍💼 Мне откликнулись", callback_data=f"{CB_RESPONDS_ROLE}:author")],
            [InlineKeyboardButton(text="↩️ В меню", callback_data=CB_DIAG_BACK)],
        ]
    )


def _responds_role_kb(side: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Активные", callback_data=f"{CB_RESPONDS_BUCKET}:{side}:active:0")],
            [InlineKeyboardButton(text="🔴 Закрытые", callback_data=f"{CB_RESPONDS_BUCKET}:{side}:closed:0")],
            [InlineKeyboardButton(text="↩️ Мои отклики", callback_data=CB_RESPONDS_ROOT)],
        ]
    )


def _responds_bucket_kb(
    *,
    side: str,
    bucket: str,
    page: int,
    items: list[Respond],
    total: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for r in items:
        rows.append([
            InlineKeyboardButton(
                text=_respond_button_text(r),
                callback_data=f"{CB_RESPOND_OPEN_FROM_LIST}:{int(r.id)}:{side}:{bucket}:{page}",
            )
        ])

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Пред. страница",
                callback_data=f"{CB_RESPONDS_BUCKET}:{side}:{bucket}:{page - 1}",
            )
        )
    if (page + 1) * RESPONDS_PAGE_SIZE < total:
        nav_row.append(
            InlineKeyboardButton(
                text="➡️ След. страница",
                callback_data=f"{CB_RESPONDS_BUCKET}:{side}:{bucket}:{page + 1}",
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data=f"{CB_RESPONDS_ROLE}:{side}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _get_channel_username_from_runtime() -> str:
    try:
        cfg = getattr(runtime, "CONFIG", None)
        if not cfg:
            return ""
        return getattr(cfg, "channel_username", "") or ""
    except Exception:
        return ""


def _get_redis() -> Any:
    return getattr(runtime, "REDIS", None)


async def _store_menu_message_id(user_id: int, message_id: int) -> None:
    r = _get_redis()
    if not r:
        return
    with contextlib.suppress(Exception):
        await r.set(MENU_MSG_KEY.format(user_id=int(user_id)), str(int(message_id)), ex=7 * 24 * 60 * 60)


async def _load_menu_message_id(user_id: int) -> int | None:
    r = _get_redis()
    if not r:
        return None
    try:
        raw = await r.get(MENU_MSG_KEY.format(user_id=int(user_id)))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        return int(str(raw).strip())
    except Exception:
        return None


async def _clear_menu_message_id(user_id: int) -> None:
    r = _get_redis()
    if not r:
        return
    with contextlib.suppress(Exception):
        await r.delete(MENU_MSG_KEY.format(user_id=int(user_id)))


async def _delete_menu_message_if_exists(bot, user_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    with contextlib.suppress(Exception):
        await bot.delete_message(chat_id=int(user_id), message_id=int(message_id))


async def _render_menu_surface(
    *,
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str | None = "HTML",
) -> None:
    user = target.from_user
    if not user:
        return

    user_id = int(user.id)
    bot = target.bot

    preferred_msg_id: int | None = None
    if isinstance(target, CallbackQuery) and target.message is not None:
        preferred_msg_id = int(target.message.message_id)

    stored_msg_id = await _load_menu_message_id(user_id)

    if isinstance(target, CallbackQuery):
        with contextlib.suppress(Exception):
            await target.answer()

    async def _try_edit(message_id: int) -> bool:
        try:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=int(message_id),
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return True
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return True
            return False

    if preferred_msg_id:
        ok = await _try_edit(preferred_msg_id)
        if ok:
            if stored_msg_id and stored_msg_id != preferred_msg_id:
                await _delete_menu_message_if_exists(bot, user_id, stored_msg_id)
            await _store_menu_message_id(user_id, preferred_msg_id)
            return

    if stored_msg_id and stored_msg_id != preferred_msg_id:
        ok = await _try_edit(stored_msg_id)
        if ok:
            await _store_menu_message_id(user_id, stored_msg_id)
            return

    try:
        m = await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception:
        return

    if stored_msg_id and stored_msg_id != int(m.message_id):
        await _delete_menu_message_if_exists(bot, user_id, stored_msg_id)

    await _store_menu_message_id(user_id, int(m.message_id))


def _preview_nav_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text="⬅️ В диагностику", callback_data=CB_DIAG)],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data=CB_DIAG_BACK)],
    ]


def _merge_keyboards(base_kb: InlineKeyboardMarkup | None, extra_rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if base_kb and getattr(base_kb, "inline_keyboard", None):
        rows.extend(base_kb.inline_keyboard)
    rows.extend(extra_rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_pending_preview_surface(target: CallbackQuery, ad) -> None:
    """
    Полноценный preview pending-объявления:
    - тот же текст get_ad_text(ad)
    - те же media (photo/video)
    - НО keyboard только stub «объявление уже отправлено на модерацию»
    + наши кнопки возврата в диагностику/меню
    """
    user = target.from_user
    if not user:
        return

    user_id = int(user.id)
    bot = target.bot

    with contextlib.suppress(Exception):
        await target.answer()

    current_msg_id: int | None = None
    if target.message is not None:
        current_msg_id = int(target.message.message_id)

    stored_msg_id = await _load_menu_message_id(user_id)
    delete_candidates: list[int] = []
    if current_msg_id:
        delete_candidates.append(current_msg_id)
    if stored_msg_id and stored_msg_id not in delete_candidates:
        delete_candidates.append(stored_msg_id)

    role = str(getattr(ad, "role", "") or "").strip().lower()
    payload = getattr(ad, "payload", None) or {}

    from findex_bot.utils.vacancy_utils import get_ad_text
    from findex_bot.utils.ui_utils import sent_to_moderation_stub_kb

    text = get_ad_text(ad)
    kb = _merge_keyboards(sent_to_moderation_stub_kb(), _preview_nav_rows())

    msg = None
    if role == "seeker":
        photo_id = str(payload.get("photo_file_id") or "").strip() or None
        if photo_id:
            msg = await bot.send_photo(
                chat_id=user_id,
                photo=photo_id,
                caption=text,
                reply_markup=kb,
            )
        else:
            msg = await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
            )
    else:
        from findex_bot.handlers import employer as employer_mod  # type: ignore

        photo_id = None
        with contextlib.suppress(Exception):
            photo_id = employer_mod._get_primary_photo_id(payload)
        if photo_id:
            photo_id = str(photo_id).strip() or None
        video_id = str(payload.get("video_file_id") or "").strip() or None

        if video_id:
            msg = await bot.send_video(
                chat_id=user_id,
                video=video_id,
                caption=text,
                reply_markup=kb,
            )
        elif photo_id:
            msg = await bot.send_photo(
                chat_id=user_id,
                photo=photo_id,
                caption=text,
                reply_markup=kb,
            )
        else:
            msg = await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
            )

    await _store_menu_message_id(user_id, int(msg.message_id))

    for mid in delete_candidates:
        if mid and mid != int(msg.message_id):
            await _delete_menu_message_if_exists(bot, user_id, mid)


async def _limit_banner_for_user(user_id: int, username: str | None) -> Optional[str]:
    moderators = set(getattr(runtime, "MODERATORS", set()) or set())
    if int(user_id) in moderators:
        return None

    if is_unlimited(int(user_id), username):
        return None

    published = 0
    try:
        async with get_sessionmaker()() as session:
            published = await db_get_pub_count(session, int(user_id))
            await session.commit()
    except Exception:
        published = 0

    limit = int(DAILY_FREE_LIMIT)
    if published < limit:
        return None

    left = format_hhmmss(utc_seconds_to_reset())
    return f"⛔ <b>Лимит исчерпан</b> ({published}/{limit}) · до сброса (UTC): <b>{left}</b>\n\n"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_relative_dt(dt: datetime | None) -> str:
    dt = _normalize_dt(dt)
    if dt is None:
        return "—"

    delta = _now_utc() - dt
    seconds = int(max(delta.total_seconds(), 0))

    if seconds < 60:
        return "только что"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}м назад"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}ч назад"

    days = hours // 24
    if days == 1:
        return "вчера"

    return f"{days}д назад"


def _coalesce_last_activity(r: Respond) -> datetime | None:
    candidates = [
        _normalize_dt(getattr(r, "closed_at", None)),
        _normalize_dt(getattr(r, "last_author_activity_at", None)),
        _normalize_dt(getattr(r, "last_candidate_activity_at", None)),
        _normalize_dt(getattr(r, "invited_at", None)),
        _normalize_dt(getattr(r, "created_at", None)),
    ]
    vals = [v for v in candidates if v is not None]
    return max(vals) if vals else None


def _thread_count(r: Respond) -> int:
    structured = getattr(r, "structured", None)
    if not isinstance(structured, dict):
        return 0

    thread = structured.get("thread")
    if not isinstance(thread, list):
        return 0

    cnt = 0
    for item in thread:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            cnt += 1
    return cnt


def _role_icon(r: Respond) -> str:
    role = str(getattr(r, "ad_role", "") or "").strip().lower()
    if role == "seeker":
        return "🙋"
    return "💼"


def _salary_text(r: Respond) -> str | None:
    payload = getattr(r, "ad_payload_snapshot", None) or {}
    salary = str(payload.get("salary") or "").strip()
    return salary or None


def _status_label(status: str, side: str, owner_viewed_at) -> str:
    st = (status or "").strip().upper()

    if st == "NEW":
        if side == "author":
            return "🆕 Новый" if owner_viewed_at is None else "🕒 Ожидает решения"
        return "🕒 На рассмотрении"

    if st == "INVITED":
        return "🎉 Приглашение отправлено" if side == "author" else "📨 Приглашение получено"

    if st == "IN_DIALOG":
        return "💬 Диалог"

    if st == "CLOSED_BY_OWNER":
        return "🚫 Закрыт работодателем"

    if st == "CLOSED_BY_CANDIDATE":
        return "🚫 Закрыт кандидатом"

    if st == "CLOSED_SYSTEM":
        return "🚫 Закрыт системой"

    return st or "—"


def _respond_title_location(r: Respond) -> tuple[str, str]:
    payload = getattr(r, "ad_payload_snapshot", None) or {}
    title = str(payload.get("title") or "").strip() or "Без названия"
    location = str(payload.get("location") or "").strip()
    return title, location


def _unread_badge(r: Respond, *, side: str) -> str | None:
    status = str(getattr(r, "status", "") or "").strip().upper()

    if side == "author":
        if status == "NEW" and getattr(r, "owner_viewed_at", None) is None:
            return "🔴 Новый отклик"

        cand_dt = _normalize_dt(getattr(r, "last_candidate_activity_at", None))
        author_dt = _normalize_dt(getattr(r, "last_author_activity_at", None))
        if cand_dt and (author_dt is None or cand_dt > author_dt):
            return "🔴 Новый ответ"
        return None

    author_candidates = [
        _normalize_dt(getattr(r, "last_author_activity_at", None)),
        _normalize_dt(getattr(r, "invited_at", None)),
    ]
    author_dt = max([v for v in author_candidates if v is not None], default=None)
    cand_dt = _normalize_dt(getattr(r, "last_candidate_activity_at", None))

    if author_dt and (cand_dt is None or author_dt > cand_dt):
        status_now = str(getattr(r, "status", "") or "").strip().upper()
        if status_now == "INVITED":
            return "🔴 Приглашение"
        return "🔴 Новый ответ"

    return None


def _respond_button_text(r: Respond) -> str:
    title, location = _respond_title_location(r)
    ad_id = int(getattr(r, "ad_id", 0) or 0)

    short_title = title[:36].rstrip()
    if len(title) > 36:
        short_title += "…"

    if location:
        short_loc = location[:18].rstrip()
        if len(location) > 18:
            short_loc += "…"
        return f"🔎 #{ad_id} · {short_title} — {short_loc}"

    return f"🔎 #{ad_id} · {short_title}"


def _responds_root_text() -> str:
    return (
        "📩 <b>Мои отклики</b>\n\n"
        "⚡ Все отклики и диалоги в одном месте\n\n"
        "Следи за статусами, отвечай кандидатам\n"
        "и управляй общением без лишних действий\n\n"
        "Выбери раздел:"
    )


def _responds_role_text(side: str, counts: dict[str, int]) -> str:
    title = "👤 <b>Я откликался</b>" if side == "candidate" else "🧑‍💼 <b>Мне откликнулись</b>"
    return (
        f"📩 <b>Мои отклики</b>\n\n"
        f"{title}\n\n"
        f"⚡ Управляй откликами и диалогами\n\n"
        f"🟢 Активные: <b>{int(counts.get('active', 0))}</b>\n"
        f"🔴 Закрытые: <b>{int(counts.get('closed', 0))}</b>\n\n"
        "Выбери раздел:"
    )


def _group_header_for_status(status: str, side: str) -> str:
    st = (status or "").strip().upper()

    if st == "INVITED":
        return "🎉 <b>Приглашения</b>"

    if st == "IN_DIALOG":
        return "💬 <b>Диалоги</b>"

    if st == "NEW":
        if side == "author":
            return "🆕 <b>Новые отклики</b>"
        return "🕒 <b>На рассмотрении</b>"

    return "📂 <b>Другое</b>"


def _respond_preview_lines(r: Respond, *, side: str, idx: int) -> list[str]:
    title, location = _respond_title_location(r)
    status = _status_label(str(getattr(r, "status", None) or ""), side, getattr(r, "owner_viewed_at", None))
    ad_id = int(getattr(r, "ad_id", 0) or 0)

    role_icon = _role_icon(r)
    salary = _salary_text(r)
    rel_time = _fmt_relative_dt(_coalesce_last_activity(r))
    unread = _unread_badge(r, side=side)
    msg_count = _thread_count(r)

    line1 = f"{idx}. {role_icon} <b>#{ad_id}</b> {title}"
    if location:
        line1 += f" — {location}"

    meta: list[str] = []
    if salary:
        meta.append(f"💰 {salary}")
    meta.append(status)
    meta.append(rel_time)

    line2 = " · ".join(meta)

    extra: list[str] = []
    if msg_count > 0:
        extra.append(f"💬 {msg_count} сообщ.")
    if unread:
        extra.append(unread)

    lines = [line1, line2]
    if extra:
        lines.append(" · ".join(extra))

    return lines


def _responds_bucket_text(side: str, bucket: str, page: int, total: int, items: list[Respond]) -> str:
    role_title = "👤 <b>Я откликался</b>" if side == "candidate" else "🧑‍💼 <b>Мне откликнулись</b>"
    bucket_title = "🟢 <b>Активные</b>" if bucket == "active" else "🔴 <b>Закрытые</b>"

    lines = [
        "📩 <b>Мои отклики</b>",
        "",
        "⚡ Отклик → диалог → результат",
        "",
        role_title,
        bucket_title,
        "",
    ]

    if not items:
        if side == "candidate":
            return (
                "📩 <b>Мои отклики</b>\n\n"
                "⚡ Отклик → диалог → результат\n\n"
                "👤 <b>Я откликался</b>\n"
                "🟢 <b>Активные</b>" if bucket == "active" else "🔴 <b>Закрытые</b>"
            ) + (
                "\n\n"
                "Пока откликов нет\n\n"
                "⚡ Найди вакансию и откликнись\n"
                "Работодатель ответит прямо в диалоге\n\n"
                "Начни прямо сейчас 👇"
            )
        else:
            return (
                "📩 <b>Мои отклики</b>\n\n"
                "⚡ Отклик → диалог → результат\n\n"
                "🧑‍💼 <b>Мне откликнулись</b>\n"
                "🟢 <b>Активные</b>" if bucket == "active" else "🔴 <b>Закрытые</b>"
            ) + (
                "\n\n"
                "Пока откликов нет\n\n"
                "⚡ Кандидаты появляются сразу после публикации\n"
                "Начни получать отклики уже сегодня\n\n"
                "Размести вакансию /start"
            )

    start_idx = page * RESPONDS_PAGE_SIZE + 1
    end_idx = min(page * RESPONDS_PAGE_SIZE + len(items), total)
    lines.append(f"Показано: <b>{start_idx}-{end_idx}</b> из <b>{total}</b>")
    lines.append("")

    prev_group: str | None = None

    for idx, r in enumerate(items, start=start_idx):
        status = str(getattr(r, "status", "") or "").strip().upper()

        if bucket == "active":
            group = _group_header_for_status(status, side)
            if group != prev_group:
                if prev_group is not None:
                    lines.append("")
                lines.append(group)
                lines.append("")
                prev_group = group

        lines.extend(_respond_preview_lines(r, side=side, idx=idx))
        lines.append("")

    return "\n".join(lines).rstrip()




MENU_SURFACE_KEY = "menu:surface:{user_id}"
MENU_SURFACE_ROOT = "root"
MENU_SURFACE_DIAG_PUBLICATION = "diag_publication"
MENU_SURFACE_DIAG_PENDING_CARD = "diag_pending_card"
MENU_SURFACE_RESPONDS_ROOT = "responds_root"


async def _set_menu_surface(user_id: int, surface: str) -> None:
    shadow_surface = {
        "root": "menu_root",
        "diag_publication": "menu_diag_publication",
        "diag_pending_card": "menu_diag_pending_card",
        "alerts_root": "menu_alerts_root",
        "responds_root": "menu_responds_root",
    }.get(str(surface), str(surface))

    with contextlib.suppress(Exception):
        await enter_surface(int(user_id), shadow_surface)

    r = getattr(runtime, "REDIS", None)
    if r is None:
        return
    await r.set(MENU_SURFACE_KEY.format(user_id=int(user_id)), str(surface), ex=3600)


async def _clear_menu_surface(user_id: int) -> None:
    with contextlib.suppress(Exception):
        await clear_surface(int(user_id))

    r = getattr(runtime, "REDIS", None)
    if r is None:
        return
    await r.delete(MENU_SURFACE_KEY.format(user_id=int(user_id)))


async def _send_or_edit_menu(target: Message | CallbackQuery):
    user = target.from_user
    if not user:
        return

    user_id = int(user.id)
    username = getattr(user, "username", None)

    with contextlib.suppress(Exception):
        await _set_menu_surface(user_id, MENU_SURFACE_ROOT)

    kb = _menu_kb(_get_channel_username_from_runtime())
    banner = await _limit_banner_for_user(user_id, username)

    text = (
        f"{banner or ''}"
        "📋 <b>FindexHub</b>\n\n"
        "⚡ Быстрые вакансии без ожидания\n\n"
        "Отклик → диалог → результат\n\n"
        "Управляй откликами, находи кандидатов\n"
        "и получай ответы без ожидания\n\n"
        "Выбери действие:"
    )

    if banner:
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="🔄 Обновить", callback_data=CB_REFRESH)])

    if isinstance(target, Message):
        bot = target.bot
        stored_msg_id = await _load_menu_message_id(user_id)

        try:
            m = await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            return

        if stored_msg_id and stored_msg_id != int(m.message_id):
            await _delete_menu_message_if_exists(bot, user_id, stored_msg_id)

        await _store_menu_message_id(user_id, int(m.message_id))
        return

    await _render_menu_surface(
        target=target,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )


async def _send_or_edit_diagnostics(target: Message | CallbackQuery):
    user = target.from_user
    if not user:
        return

    user_id = int(user.id)
    with contextlib.suppress(Exception):
        await _set_menu_surface(user_id, MENU_SURFACE_DIAG_PUBLICATION)
    username = getattr(user, "username", None)
    diag = _diag_mod()

    text, kb = await diag.build_diagnostics_view(
        user_id=int(user_id),
        username=username,
        bot=target.bot,
        include_menu_back=True,
    )

    await _render_menu_surface(
        target=target,
        text=text,
        reply_markup=kb or InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="↩️ В меню", callback_data=CB_DIAG_BACK)],
            ]
        ),
        parse_mode=None,
    )


async def _send_or_edit_pending_ad(target: Message | CallbackQuery, ad_id: int):
    if not isinstance(target, CallbackQuery):
        return

    user = target.from_user
    if not user:
        return

    with contextlib.suppress(Exception):
        await _set_menu_surface(int(user.id), MENU_SURFACE_DIAG_PENDING_CARD)

    diag = _diag_mod()
    ad = await diag.get_pending_ad_for_user(int(user.id), int(ad_id))

    if ad is None:
        with contextlib.suppress(Exception):
            await target.answer("⚠️ Объявление уже не находится на модерации", show_alert=True)
        await _send_or_edit_diagnostics(target)
        return

    await _render_pending_preview_surface(target, ad)


async def _send_or_edit_responds_root(target: Message | CallbackQuery):
    user = target.from_user
    if user:
        with contextlib.suppress(Exception):
            await _set_menu_surface(int(user.id), MENU_SURFACE_RESPONDS_ROOT)

    text = _responds_root_text()
    kb = _responds_root_kb()

    await _render_menu_surface(
        target=target,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )


async def _send_or_edit_responds_role(target: Message | CallbackQuery, side: str):
    user = target.from_user
    if not user:
        return

    with contextlib.suppress(Exception):
        await _set_menu_surface(int(user.id), MENU_SURFACE_RESPONDS_ROOT)

    async with get_sessionmaker()() as session:
        repo = RespondRepo(session)
        counts = await repo.counts_for_user(user_id=int(user.id), side=side)

    text = _responds_role_text(side, counts)
    kb = _responds_role_kb(side)

    await _render_menu_surface(
        target=target,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )


async def _send_or_edit_responds_bucket(target: Message | CallbackQuery, side: str, bucket: str, page: int):
    user = target.from_user
    if not user:
        return

    with contextlib.suppress(Exception):
        await _set_menu_surface(int(user.id), MENU_SURFACE_RESPONDS_ROOT)

    offset = max(page, 0) * RESPONDS_PAGE_SIZE

    async with get_sessionmaker()() as session:
        repo = RespondRepo(session)
        total = await repo.count_for_user(user_id=int(user.id), side=side, bucket=bucket)
        items = await repo.list_for_user(
            user_id=int(user.id),
            side=side,
            bucket=bucket,
            limit=RESPONDS_PAGE_SIZE,
            offset=offset,
        )

    text = _responds_bucket_text(side, bucket, max(page, 0), total, items)
    kb = _responds_bucket_kb(
        side=side,
        bucket=bucket,
        page=max(page, 0),
        items=items,
        total=total,
    )

    await _render_menu_surface(
        target=target,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def menu_cmd(message: Message, state: FSMContext):
    with contextlib.suppress(Exception):
        await state.clear()

    with contextlib.suppress(Exception):
        r = getattr(runtime, "REDIS", None)
        if r is not None:
            await r.delete(f"respond:active_view:{int(message.from_user.id)}")

    with contextlib.suppress(Exception):
        await message.delete()

    log_event(
        logger,
        "menu_open",
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        source="command",
        result="ok",
    )
    await _send_or_edit_menu(message)


@router.callback_query(F.data == CB_REFRESH)
async def menu_refresh(callback: CallbackQuery, state: FSMContext):
    with contextlib.suppress(Exception):
        await state.clear()
    log_event(
        logger,
        "menu_refresh",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        result="ok",
    )
    await _send_or_edit_menu(callback)


@router.callback_query(F.data == CB_DIAG)
async def menu_diag(callback: CallbackQuery, state: FSMContext):
    with contextlib.suppress(Exception):
        await state.clear()
    log_event(
        logger,
        "menu_diag_open",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        result="ok",
    )
    await _send_or_edit_diagnostics(callback)


@router.callback_query(F.data == CB_DIAG_BACK)
async def menu_diag_back(callback: CallbackQuery, state: FSMContext):
    with contextlib.suppress(Exception):
        await state.clear()
    log_event(
        logger,
        "menu_diag_back",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        result="ok",
    )
    await _send_or_edit_menu(callback)


@router.callback_query(F.data.startswith(f"{CB_DIAG_PENDING_OPEN}:"))
async def menu_diag_pending_open(callback: CallbackQuery, state: FSMContext):
    parts = (callback.data or "").split(":")
    if len(parts) != 2:
        log_event(
            logger,
            "menu_diag_pending_open",
            user_id=callback.from_user.id,
            callback_data=callback.data,
            result="fail",
        )
        with contextlib.suppress(Exception):
            await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return

    try:
        ad_id = int(parts[1])
    except Exception:
        with contextlib.suppress(Exception):
            await callback.answer("⚠️ Некорректные данные", show_alert=True)
        return

    with contextlib.suppress(Exception):
        await state.clear()
    with contextlib.suppress(Exception):
        await _set_menu_surface(int(callback.from_user.id), MENU_SURFACE_DIAG_PENDING_CARD)
    log_event(
        logger,
        "menu_diag_pending_open",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        ad_id=ad_id,
        result="ok",
    )
    await _send_or_edit_pending_ad(callback, ad_id)


@router.callback_query(F.data == CB_RESPONDS_ROOT)
async def menu_responds_root(callback: CallbackQuery, state: FSMContext):
    with contextlib.suppress(Exception):
        await state.clear()
    log_event(
        logger,
        "menu_responds_root_open",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        result="ok",
    )
    await _send_or_edit_responds_root(callback)


@router.callback_query(F.data.startswith(f"{CB_RESPONDS_ROLE}:"))
async def menu_responds_role(callback: CallbackQuery, state: FSMContext):
    parts = (callback.data or "").split(":")
    if len(parts) != 2:
        log_event(
            logger,
            "menu_responds_role_open",
            user_id=callback.from_user.id,
            callback_data=callback.data,
            result="fail",
        )
        try:
            await callback.answer("⚠️ Некорректные данные", show_alert=True)
        except Exception:
            pass
        return

    side = parts[1].strip()
    if side not in {"candidate", "author"}:
        try:
            await callback.answer("⚠️ Некорректные данные", show_alert=True)
        except Exception:
            pass
        return

    with contextlib.suppress(Exception):
        await state.clear()
    log_event(
        logger,
        "menu_responds_role_open",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        side=side,
        result="ok",
    )
    await _send_or_edit_responds_role(callback, side)


@router.callback_query(F.data.startswith(f"{CB_RESPONDS_BUCKET}:"))
async def menu_responds_bucket(callback: CallbackQuery, state: FSMContext):
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        log_event(
            logger,
            "menu_responds_bucket_open",
            user_id=callback.from_user.id,
            callback_data=callback.data,
            result="fail",
        )
        try:
            await callback.answer("⚠️ Некорректные данные", show_alert=True)
        except Exception:
            pass
        return

    side = parts[1].strip()
    bucket = parts[2].strip()
    try:
        page = int(parts[3])
    except Exception:
        page = 0

    if side not in {"candidate", "author"} or bucket not in {"active", "closed"}:
        try:
            await callback.answer("⚠️ Некорректные данные", show_alert=True)
        except Exception:
            pass
        return

    with contextlib.suppress(Exception):
        r = getattr(runtime, "REDIS", None)
        if r is not None:
            await r.delete(f"respond:active_view:{int(callback.from_user.id)}")

    with contextlib.suppress(Exception):
        await _set_menu_surface(int(callback.from_user.id), MENU_SURFACE_RESPONDS_ROOT)

    log_event(
        logger,
        "menu_responds_bucket_open",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        side=side,
        bucket=bucket,
        page=max(page, 0),
        result="ok",
    )
    await _send_or_edit_responds_bucket(callback, side, bucket, max(page, 0))


@router.callback_query(F.data == CB_START)
async def menu_start(callback: CallbackQuery, state: FSMContext):
    log_event(
        logger,
        "menu_start_roles",
        user_id=callback.from_user.id,
        callback_data=callback.data,
        result="ok",
    )
    await show_roles(callback, state)
