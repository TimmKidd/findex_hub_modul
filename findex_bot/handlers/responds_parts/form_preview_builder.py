from __future__ import annotations

from typing import Any


def build_form_preview_payload(
    *,
    data: dict[str, Any],
    ad_id: int,
    candidate_profile_from_state_fn,
    profile_has_resume_fn,
    render_profile_lines_fn,
    form_preview_kb_fn,
) -> tuple[str, object, bool]:
    prof = candidate_profile_from_state_fn(data)
    has_resume = profile_has_resume_fn(prof)

    text = (
        "✅ <b>Проверь анкету</b>\n\n"
        + "\n".join(render_profile_lines_fn(prof))
        + "\n\n"
        "✏️ Чтобы изменить конкретное поле — нажми на кнопку ниже.\n"
        "Если всё верно — нажми «📨 Отправить отклик»."
    )

    kb = form_preview_kb_fn(ad_id, has_resume=has_resume)

    return text, kb, has_resume
