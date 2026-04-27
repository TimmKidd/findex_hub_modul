import pytest
from findex_bot.utils.vacancy_utils import (
    contains_bad_words,
    is_valid_city_input,
    get_ad_text
)


# ----------------------------
# TEST contains_bad_words()
# ----------------------------

def test_contains_bad_words_detects_curse():
    assert contains_bad_words("это жопа") is True
    assert contains_bad_words("какая-то хуйня") is True
    assert contains_bad_words("блядь ну почему") is True


def test_contains_bad_words_clean_text():
    assert contains_bad_words("Прекрасная вакансия, приходите!") is False
    assert contains_bad_words("мир дружба жвачка") is False


# ----------------------------
# TEST is_valid_city_input()
# ----------------------------

def test_city_valid_inputs():
    assert is_valid_city_input("Москва") is True
    assert is_valid_city_input("Санкт-Петербург") is True
    assert is_valid_city_input("Нижний Новгород") is True


def test_city_invalid_inputs():
    assert is_valid_city_input("Москва123") is False
    assert is_valid_city_input("Hello") is False
    assert is_valid_city_input("@Москва") is False
    assert is_valid_city_input("Пи$ец") is False


# ----------------------------
# TEST get_ad_text()
# ----------------------------

def test_get_ad_text_employer():
    data = {
        "role": "Работодатель",
        "position": "Бармен",
        "salary": "120000",
        "location": "Москва",
        "contacts": "@test",
        "description": "Хороший коллектив",
        "author": "@user",
    }

    text = get_ad_text(data, include_author=True)

    assert "Бармен" in text
    assert "120000" in text
    assert "Москва" in text
    assert "@test" in text
    assert "Хороший коллектив" in text
    assert "@user" in text


def test_get_ad_text_seeker():
    data = {
        "role": "Соискатель",
        "position": "Бариста",
        "schedule": "Полный день",
        "salary": "80000",
        "location": "СПб",
        "contacts": "@me",
        "description": "Опыт 2 года",
        "author": "@usr"
    }

    text = get_ad_text(data, include_author=False)

    assert "Бариста" in text
    assert "Полный день" in text
    assert "80000" in text
    assert "СПб" in text
    assert "@me" in text
    assert "Опыт 2 года" in text
    assert "@usr" not in text  # автор скрыт

