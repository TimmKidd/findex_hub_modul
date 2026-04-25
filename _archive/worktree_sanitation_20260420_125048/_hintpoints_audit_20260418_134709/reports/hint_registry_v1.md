# Hint Registry v1

Статус:
- live зон: 11
- target зон: 1
- всего зон: 12

## 1. welcome_roles_trash
- status: live
- ux_condition: мусор под экраном выбора роли
- ux_points: 1
- canonical_text: Нажми одну из кнопок выше: 🏢 Работодатель или 👤 Соискатель.
- current_code_source: findex_bot/handlers/start.py:90 :: WELCOME_CLEAN_THREAD_HINT

## 2. vacancy_contact_mode_trash
- status: live
- ux_condition: мусор под экраном выбора способа получения откликов
- ux_points: 2
- canonical_text: Нажми одну из кнопок выше: 🔒 Отклики через бота или 📞 Контакты в объявлении.
- current_code_source: findex_bot/middlewares/fsm_watchdog.py:66 :: _clean_thread_hint_for_state

## 3. vacancy_media_choice_trash
- status: live
- ux_condition: мусор под экраном выбора медиа
- ux_points: 2
- canonical_text: Нажми одну из кнопок выше: ➕ Добавить медиа или ⏭ Без медиа.
- current_code_source: findex_bot/middlewares/fsm_watchdog.py:69 :: _clean_thread_hint_for_state

## 4. vacancy_media_confirm_trash
- status: live
- ux_condition: мусор под экраном подтверждения медиа
- ux_points: 2
- canonical_text: Нажми одну из кнопок выше: ✅ Подтвердить, 🔁 Заменить или 🗑 Удалить.
- current_code_source: findex_bot/middlewares/fsm_watchdog.py:87 :: _clean_thread_hint_for_state

## 5. vacancy_preview_trash
- status: live
- ux_condition: мусор под preview объявления до отправки на модерацию
- ux_points: 2
- canonical_text: Используй кнопки выше: исправить поле, изменить медиа или отправить объявление на модерацию.
- current_code_source:
  - findex_bot/handlers/employer.py:1027 :: employer_buttons_only_trash
  - findex_bot/handlers/seeker.py:988 :: seeker_buttons_only_trash
  - findex_bot/middlewares/fsm_watchdog.py:90 :: _clean_thread_hint_for_state

## 6. vacancy_on_moderation_trash
- status: live
- ux_condition: мусор под preview объявления, которое уже отправлено на модерацию
- ux_points: 2
- canonical_text: ⏳ Объявление уже отправлено на модерацию. Дождись ответа модератора.
- current_code_source:
  - findex_bot/handlers/employer.py:1025 :: employer_buttons_only_trash
  - findex_bot/handlers/seeker.py:986 :: seeker_buttons_only_trash

## 7. respond_intro_choice_trash
- status: live
- ux_condition: мусор под intro-карточкой отклика до старта быстрого отклика
- ux_points: 1
- canonical_text: 👆 Нажми кнопку «⚡ Откликнуться за 1 минуту» выше.
- current_code_source:
  - findex_bot/handlers/responds.py:1027 :: _send_intro_trash_hint
  - findex_bot/middlewares/fsm_watchdog.py:75 :: _clean_thread_hint_for_state

## 8. respond_saved_choice_trash
- status: live
- ux_condition: мусор под экраном выбора между быстрым откликом и перезапуском заполнения
- ux_points: 1
- canonical_text: Нажми одну из кнопок выше: ⚡ Быстрый отклик или ✏️ Заполнить заново.
- current_code_source: findex_bot/middlewares/fsm_watchdog.py:78 :: _clean_thread_hint_for_state

## 9. respond_form_preview_trash
- status: live
- ux_condition: мусор под preview анкеты отклика перед отправкой
- ux_points: 1
- canonical_text: Используй кнопки выше: измени поле или отправь отклик.
- current_code_source: findex_bot/middlewares/fsm_watchdog.py:81 :: _clean_thread_hint_for_state

## 10. respond_existing_notice_trash
- status: live
- ux_condition: мусор под notice-экраном, где уже существует отклик на это объявление
- ux_points: 1
- canonical_text: Используй кнопку «Открыть мой отклик» в карточке выше.
- current_code_source: findex_bot/handlers/responds.py:3449 :: form_existing_notice_clean_thread

## 11. respond_citizenship_pick_trash
- status: live
- ux_condition: мусор под экраном выбора гражданства в анкете отклика
- ux_points: 1
- canonical_text: Здесь нужно выбрать гражданство кнопкой выше. Если страны нет в списке — нажми «🌍 Другая страна».
- current_code_source: findex_bot/middlewares/fsm_watchdog.py:84 :: _clean_thread_hint_for_state

## 12. respond_active_card_trash
- status: target
- ux_condition: мусор под активной карточкой отклика
- ux_points: 2
- canonical_text: Управляй откликом кнопками в карточке выше или воспользуйся /menu
- current_code_source: not_yet_separated ; future_bind_anchor = findex_bot/handlers/responds.py:63 :: ACTIVE_KEY
