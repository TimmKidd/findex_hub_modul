import datetime
import pytest

from findex_bot.bot import (
    USER_PUB_COUNTER,
    UNLIMITED_USERS,
    check_and_update_limit,
    increment_pub_counter
)


# ---------- ФИКСАТУРЫ ----------
@pytest.fixture(autouse=True)
def clean_storage():
    """Перед каждым тестом очищаем счетчики."""
    USER_PUB_COUNTER.clear()
    UNLIMITED_USERS.clear()
    UNLIMITED_USERS.update({80675147, 7107629211})
    yield
    USER_PUB_COUNTER.clear()


# ---------- ТЕСТЫ ----------
def test_unlimited_user_has_no_limit():
    user_id = 80675147  # модератор

    can_post, remaining = check_and_update_limit(user_id)

    assert can_post is True
    assert remaining == "∞"  # для безлимита возвращаем бесконечность


def test_first_publication():
    user_id = 123

    can_post, remaining = check_and_update_limit(user_id)

    assert can_post is True
    assert remaining == 2  # было 0/3, стало 1/3 → осталось 2


def test_three_publications_limit():
    user_id = 555

    # 1 публикация
    check_and_update_limit(user_id)
    # 2 публикация
    check_and_update_limit(user_id)
    # 3 публикация
    can_post, remaining = check_and_update_limit(user_id)

    assert can_post is True
    assert remaining == 0  # 3/3


def test_fourth_publication_blocked():
    user_id = 888

    # 3 публикации
    check_and_update_limit(user_id)
    check_and_update_limit(user_id)
    check_and_update_limit(user_id)

    # 4 — должна быть заблокирована
    can_post, remaining = check_and_update_limit(user_id)

    assert can_post is False
    assert remaining == 0


def test_new_day_resets_counter():
    user_id = 999

    # 1 публикация сегодня
    check_and_update_limit(user_id)

    # подменяем дату на вчерашнюю
    USER_PUB_COUNTER[user_id]["date"] = "2000-01-01"

    # новая публикация должна пройти как первая
    can_post, remaining = check_and_update_limit(user_id)

    assert can_post is True
    assert remaining == 2  # снова 1/3


def test_increment_pub_counter():
    user_id = 222

    increment_pub_counter(user_id)
    increment_pub_counter(user_id)

    assert USER_PUB_COUNTER[user_id]["count"] == 2

