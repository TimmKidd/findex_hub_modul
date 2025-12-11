from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from findex_bot.config import MODERATION_CHAT_ID, CHANNEL_ID
from findex_bot.handlers.common import (
    FIELDS,
    build_post,
    generate_tags,
    parse_field_from_reason,
    user_profile_link,
)

router = Router()

class RejectReasonFSM(StatesGroup):
    waiting_for_reason = State()

MOD_MAP = {}

async def send_to_moderation(bot, text, user, user_id, photo=None, category=None, form=None):
    # Здесь text уже готов целиком (с user_profile_link)
    content = text
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_{user_id}:{user.username or user.id}"
            ),
            types.InlineKeyboardButton(
                text="⛔️ Отклонить",
                callback_data=f"reject_{user_id}:{user.username or user.id}"
            ),
        ]
    ])
    if photo:
        sent = await bot.send_photo(
            MODERATION_CHAT_ID,
            photo=photo,
            caption=content,
            parse_mode="HTML",
            reply_markup=kb
        )
    else:
        sent = await bot.send_message(
            MODERATION_CHAT_ID,
            text=content,
            parse_mode="HTML",
            reply_markup=kb
        )
    MOD_MAP[sent.message_id] = {"category": category, "form": form, "user_id": user.id, "photo_id": photo}
    return sent.message_id

@router.callback_query(F.data.startswith("approve_"))
async def approve_ad(call: types.CallbackQuery, state: FSMContext):
    msg = call.message
    moderator_id = call.from_user.id
    moderator_username = call.from_user.username or call.from_user.full_name or str(moderator_id)
    src = MOD_MAP.get(msg.message_id)
    if not src:
        await call.answer("Ошибка: Не могу найти данные для публикации.", show_alert=True)
        return
    category = src["category"]
    form_data = src["form"]
    user_id = src["user_id"]
    photo_id = src.get("photo_id")
    post_channel = build_post(category, form_data)
    tags = generate_tags(category, form_data)

    try:
        await msg.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await msg.reply(f"✅ ОДОБРЕНО модератором {moderator_username}", parse_mode="HTML")

    try:
        if photo_id:
            publish = await call.bot.send_photo(
                CHANNEL_ID,
                photo=photo_id,
                caption=post_channel + "\n\n" + tags,
                parse_mode="HTML",
            )
        else:
            publish = await call.bot.send_message(
                CHANNEL_ID,
                text=post_channel + "\n\n" + tags,
                parse_mode="HTML",
            )
        channel_id_link = str(CHANNEL_ID).replace("-100", "")
        post_url = f"https://t.me/c/{channel_id_link}/{publish.message_id}"
        await call.bot.send_message(
            user_id,
            f"✅ Ваше объявление одобрено и опубликовано!\n\nСсылка: {post_url}"
        )
        await call.answer("Объявление опубликовано!")
    except Exception as e:
        await call.answer(f"Ошибка публикации в канал: {e}", show_alert=True)

@router.callback_query(F.data.startswith("reject_"))
async def reject_ad(call: types.CallbackQuery, state: FSMContext):
    msg = call.message
    moderator_username = call.from_user.username or call.from_user.full_name or str(call.from_user.id)
    src = MOD_MAP.get(msg.message_id)
    user_id = src["user_id"] if src else None
    await state.update_data(reject_user_id=user_id, reject_msg_id=msg.message_id, chat_id=msg.chat.id, moderator_username=moderator_username, category=src["category"])
    await call.message.reply(
        "Пожалуйста, введите причину возврата объявления пользователю (она будет добавлена к объявлению):",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await call.answer()
    await state.set_state(RejectReasonFSM.waiting_for_reason)

@router.message(RejectReasonFSM.waiting_for_reason)
async def get_reject_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    reject_msg_id = data.get("reject_msg_id")
    chat_id = data.get("chat_id")
    user_id = data.get("reject_user_id")
    moderator_username = data.get("moderator_username")
    reason = message.text
    category = data.get("category")
    bot = message.bot

    try:
        await bot.edit_reply_markup(chat_id=chat_id, message_id=reject_msg_id, reply_markup=None)
        await bot.send_message(
            chat_id,
            f"❌ ОТКЛОНЕНО модератором {moderator_username}\nПричина: {reason}",
            reply_to_message_id=reject_msg_id,
            parse_mode="HTML"
        )
    except Exception:
        await message.reply("Ошибка при возврате объявления.")

    field_to_edit = parse_field_from_reason(reason, category)
    callback_field = field_to_edit if field_to_edit else ""

    reply_markup = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="✏️ Доработать объявление",
                    callback_data=f"edit_post_{reject_msg_id}|{callback_field}"
                )
            ]
        ]
    )

    await bot.send_message(
        user_id,
        f"❌ Ваше объявление отклонено модератором.\nПричина: {reason}\n\nВы можете доработать объявление и отправить его снова.",
        reply_markup=reply_markup
    )
    await message.reply("Причина отправлена пользователю. Объявление помечено как отклонённое.", reply_markup=types.ReplyKeyboardRemove())
    await state.clear()

@router.callback_query(F.data.startswith("edit_post_"))
async def edit_post_handler(call: types.CallbackQuery, state: FSMContext):
    cb_data = call.data.replace("edit_post_", "")
    if "|" in cb_data:
        reject_msg_id, field_key = cb_data.split("|")
    else:
        reject_msg_id, field_key = cb_data, ""
    src = MOD_MAP.get(int(reject_msg_id))
    if src is None:
        await call.answer("Ошибка: не удалось найти объявление для редактирования.", show_alert=True)
        return
    category = src["category"]
    form_data = src["form"]
    FIELDS_LIST = FIELDS[category]
    step = 0
    if field_key:
        for i, (key, label) in enumerate(FIELDS_LIST):
            if key == field_key:
                step = i
                break
    await state.clear()
    await state.update_data(category=category, form=form_data, step=step, photo=src.get("photo_id"))
    from findex_bot.handlers.start import start_field_edit_mode
    await start_field_edit_mode(call.message, state, step)