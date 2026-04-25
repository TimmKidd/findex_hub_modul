from __future__ import annotations

import math
import re
from typing import Any

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

METRO_PICK_CALLBACK = "metro_pick"
METRO_LINE_CALLBACK = "metro_line"
METRO_STATION_CALLBACK = "metro_station"
METRO_CLOSE_CALLBACK = "metro_close"

LINES_PER_PAGE = 8
STATIONS_PER_PAGE = 20

MOSCOW_LOCATION_PROMPT = (
    "Укажи 📍 локацию.\n"
    "Для Москвы можно указать метро вручную или выбрать его кнопкой ниже.\n\n"
    "Примеры:\n"
    "• Москва (Тверская)\n"
    "• Химки\n"
    "• Казань"
)

METRO_LINES: list[dict[str, Any]] = [
    {
        "uid": "1",
        "name": "Сокольническая",
        "title": "🔴 Сокольническая",
        "color": "#f91f22",
        "stations": [
            "Бульвар Рокоссовского", "Черкизовская", "Преображенская площадь", "Сокольники",
            "Красносельская", "Комсомольская", "Красные ворота", "Чистые пруды",
            "Лубянка", "Охотный Ряд", "Библиотека им. Ленина", "Кропоткинская",
            "Парк культуры", "Фрунзенская", "Спортивная", "Воробьёвы горы",
            "Университет", "Проспект Вернадского", "Юго-Западная", "Тропарёво",
            "Румянцево", "Саларьево", "Филатов Луг", "Прокшино",
            "Ольховая", "Коммунарка",
        ],
    },
    {
        "uid": "2",
        "name": "Замоскворецкая",
        "title": "🟢 Замоскворецкая",
        "color": "#05ff16",
        "stations": [
            "Ховрино", "Беломорская", "Речной вокзал", "Водный стадион",
            "Войковская", "Сокол", "Аэропорт", "Динамо",
            "Белорусская", "Маяковская", "Тверская", "Театральная",
            "Новокузнецкая", "Павелецкая", "Автозаводская", "Технопарк",
            "Коломенская", "Каширская", "Кантемировская", "Царицыно",
            "Орехово", "Домодедовская", "Красногвардейская", "Алма-Атинская",
        ],
    },
    {
        "uid": "3",
        "name": "Арбатско-Покровская",
        "title": "🔵 Арбатско-Покровская",
        "color": "#2075b1",
        "stations": [
            "Щёлковская", "Первомайская", "Измайловская", "Партизанская",
            "Семёновская", "Электрозаводская", "Бауманская", "Курская",
            "Площадь Революции", "Арбатская", "Смоленская", "Киевская",
            "Парк Победы", "Славянский бульвар", "Кунцевская", "Молодёжная",
            "Крылатское", "Строгино", "Мякинино", "Волоколамская",
            "Митино", "Пятницкое шоссе",
        ],
    },
    {
        "uid": "4",
        "name": "Филёвская",
        "title": "🔹 Филёвская",
        "color": "#52d2f4",
        "stations": [
            "Александровский сад", "Арбатская", "Смоленская", "Киевская",
            "Выставочная", "Международная", "Студенческая", "Кутузовская",
            "Фили", "Багратионовская", "Филёвский парк", "Пионерская",
            "Кунцевская",
        ],
    },
    {
        "uid": "5",
        "name": "Кольцевая",
        "title": "🟤 Кольцевая",
        "color": "#75573e",
        "stations": [
            "Комсомольская", "Курская", "Таганская", "Павелецкая",
            "Добрынинская", "Октябрьская", "Парк культуры", "Киевская",
            "Краснопресненская", "Белорусская", "Новослободская", "Проспект Мира",
        ],
    },
    {
        "uid": "6",
        "name": "Калужско-Рижская",
        "title": "🟠 Калужско-Рижская",
        "color": "#f6990e",
        "stations": [
            "Медведково", "Бабушкинская", "Свиблово", "Ботанический сад",
            "ВДНХ", "Алексеевская", "Рижская", "Проспект Мира",
            "Сухаревская", "Тургеневская", "Китай-город", "Третьяковская",
            "Октябрьская", "Шаболовская", "Ленинский проспект", "Академическая",
            "Профсоюзная", "Новые Черёмушки", "Калужская", "Беляево",
            "Коньково", "Тёплый стан", "Ясенево", "Новоясеневская",
        ],
    },
    {
        "uid": "7",
        "name": "Таганско-Краснопресненская",
        "title": "🟣 Таганско-Краснопресненская",
        "color": "#821c71",
        "stations": [
            "Планерная", "Сходненская", "Тушинская", "Спартак",
            "Щукинская", "Октябрьское поле", "Полежаевская", "Беговая",
            "Улица 1905 года", "Баррикадная", "Пушкинская", "Кузнецкий Мост",
            "Китай-город", "Таганская", "Пролетарская", "Волгоградский проспект",
            "Текстильщики", "Кузьминки", "Рязанский проспект", "Выхино",
            "Лермонтовский проспект", "Жулебино", "Котельники",
        ],
    },
    {
        "uid": "8",
        "name": "Калининская",
        "title": "🟡 Калининская",
        "color": "#ffcd1e",
        "stations": [
            "Третьяковская", "Марксистская", "Площадь Ильича", "Авиамоторная",
            "Шоссе Энтузиастов", "Перово", "Новогиреево", "Новокосино",
        ],
    },
    {
        "uid": "9",
        "name": "Солнцевская",
        "title": "🟨 Солнцевская",
        "color": "#ffd84d",
        "stations": [
            "Деловой центр", "Парк Победы", "Минская", "Ломоносовский проспект",
            "Раменки", "Мичуринский проспект", "Озёрная", "Говорово",
            "Солнцево", "Боровское шоссе", "Новопеределкино", "Рассказовка",
            "Пыхтино", "Аэропорт Внуково",
        ],
    },
    {
        "uid": "10",
        "name": "Серпуховско-Тимирязевская",
        "title": "⚫ Серпуховско-Тимирязевская",
        "color": "#adacac",
        "stations": [
            "Алтуфьево", "Бибирево", "Отрадное", "Владыкино",
            "Петровско-Разумовская", "Тимирязевская", "Дмитровская", "Савёловская",
            "Менделеевская", "Цветной бульвар", "Чеховская", "Боровицкая",
            "Полянка", "Серпуховская", "Тульская", "Нагатинская",
            "Нагорная", "Нахимовский проспект", "Севастопольская", "Чертановская",
            "Южная", "Пражская", "Улица Академика Янгеля", "Аннино",
            "Бульвар Дмитрия Донского",
        ],
    },
    {
        "uid": "11",
        "name": "Люблинско-Дмитровская",
        "title": "🟩 Люблинско-Дмитровская",
        "color": "#b1d332",
        "stations": [
            "Физтех", "Лианозово", "Яхромская", "Селигерская",
            "Верхние Лихоборы", "Окружная", "Петровско-Разумовская", "Фонвизинская",
            "Бутырская", "Марьина Роща", "Достоевская", "Трубная",
            "Сретенский бульвар", "Чкаловская", "Римская", "Крестьянская Застава",
            "Дубровка", "Кожуховская", "Печатники", "Волжская",
            "Люблино", "Братиславская", "Марьино", "Борисово",
            "Шипиловская", "Зябликово",
        ],
    },
    {
        "uid": "12",
        "name": "Большая кольцевая",
        "title": "🩵 Большая кольцевая",
        "color": "#82d4c7",
        "stations": [
            "Савёловская", "Марьина Роща", "Рижская", "Сокольники",
            "Электрозаводская", "Лефортово", "Авиамоторная", "Нижегородская",
            "Текстильщики", "Печатники", "Нагатинский затон", "Кленовый бульвар",
            "Каширская", "Варшавская", "Каховская", "Зюзино",
            "Воронцовская", "Новаторская", "Проспект Вернадского", "Мичуринский проспект",
            "Аминьевская", "Давыдково", "Кунцевская", "Терехово",
            "Мнёвники", "Народное Ополчение", "Хорошёвская", "ЦСКА",
            "Петровский парк", "Деловой центр",
        ],
    },
    {
        "uid": "13",
        "name": "Бутовская",
        "title": "🩶 Бутовская",
        "color": "#9fb7c7",
        "stations": [
            "Улица Старокачаловская", "Лесопарковая", "Битцевский парк", "Улица Скобелевская",
            "Бульвар Адмирала Ушакова", "Улица Горчакова", "Бунинская аллея",
        ],
    },
    {
        "uid": "14",
        "name": "Некрасовская",
        "title": "🌸 Некрасовская",
        "color": "#de64b7",
        "stations": [
            "Некрасовка", "Лухмановская", "Улица Дмитриевского", "Косино",
            "Юго-Восточная", "Окская", "Стахановская", "Нижегородская",
            "Лефортово", "Авиамоторная",
        ],
    },
    {
        "uid": "15",
        "name": "Троицкая",
        "title": "💚 Троицкая",
        "color": "#497561",
        "stations": [
            "ЗИЛ", "Крымская", "Академическая", "Вавиловская",
            "Новаторская", "Университет дружбы народов", "Генерала Тюленева", "Тютчевская",
            "Корниловская", "Коммунарка", "Новомосковская",
        ],
    },
]

LINE_BY_UID = {item["uid"]: item for item in METRO_LINES}


def metro_location_prompt() -> str:
    return MOSCOW_LOCATION_PROMPT


def metro_location_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚇 Выбрать метро Москвы", callback_data=METRO_PICK_CALLBACK)],
        ]
    )


def metro_lines_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(METRO_LINES) / LINES_PER_PAGE))
    page = max(0, min(int(page), total_pages - 1))
    start = page * LINES_PER_PAGE
    chunk = METRO_LINES[start:start + LINES_PER_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for item in chunk:
        rows.append([
            InlineKeyboardButton(
                text=f"{_line_emoji(item['color'])} {item['name']} ({len(item['stations'])})",
                callback_data=f"{METRO_LINE_CALLBACK}:{item['uid']}:0",
            )
        ])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{METRO_PICK_CALLBACK}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️ Дальше", callback_data=f"{METRO_PICK_CALLBACK}:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data=METRO_CLOSE_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def metro_stations_keyboard(line_uid: str, page: int = 0) -> InlineKeyboardMarkup:
    item = LINE_BY_UID.get(str(line_uid))
    if not item:
        return metro_lines_keyboard(0)

    stations = item["stations"]
    total_pages = max(1, math.ceil(len(stations) / STATIONS_PER_PAGE))
    page = max(0, min(int(page), total_pages - 1))
    start = page * STATIONS_PER_PAGE
    chunk = stations[start:start + STATIONS_PER_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for idx, station in enumerate(chunk, start=start):
        rows.append([
            InlineKeyboardButton(
                text=station,
                callback_data=f"{METRO_STATION_CALLBACK}:{line_uid}:{idx}",
            )
        ])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{METRO_LINE_CALLBACK}:{line_uid}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️ Дальше", callback_data=f"{METRO_LINE_CALLBACK}:{line_uid}:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="↩️ К линиям", callback_data=f"{METRO_PICK_CALLBACK}:0")])
    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data=METRO_CLOSE_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def resolve_station(line_uid: str, station_index: int) -> str | None:
    item = LINE_BY_UID.get(str(line_uid))
    if not item:
        return None
    stations = item["stations"]
    try:
        idx = int(station_index)
    except Exception:
        return None
    if idx < 0 or idx >= len(stations):
        return None
    return str(stations[idx])


def build_moscow_location(station: str) -> str:
    clean = normalize_metro_station_name(station)
    return f"Москва ({clean})"


def normalize_metro_station_name(station: str) -> str:
    s = re.sub(r"\s+", " ", str(station or "").strip())
    s = re.sub(r"^(м\.|метро)\s*", "", s, flags=re.IGNORECASE)
    return s.strip(" ,.-")


def validate_location_input(text: str) -> str | None:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return "⚠️ Укажи локацию."

    if len(raw) < 2:
        return "⚠️ Локация слишком короткая."

    if re.search(r"[^A-Za-zА-Яа-яЁё0-9\-() ,.]+", raw):
        return "⚠️ В локации используй только буквы, цифры, пробелы, дефис, скобки, точку и запятую."

    low = raw.lower()
    if low.startswith("москва"):
        if re.fullmatch(r"москва", low):
            return None
        if re.fullmatch(r"москва\s*\((?:м\.?\s*)?[а-яёa-z0-9\- ]+\)", low):
            return None
        if re.fullmatch(r"москва\s*,\s*(?:м\.?\s*)?[а-яёa-z0-9\- ]+", low):
            return None
        return "⚠️ Для Москвы укажи метро в формате: Москва (Тверская) или Москва, Тверская."

    if "," in raw:
        return "⚠️ Запятая в локации нужна только для формата Москвы с метро."

    return None


def normalize_location_input(text: str) -> str:
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    low = raw.lower()
    if low == "москва":
        return "Москва"
    m = re.fullmatch(r"москва\s*\((.+)\)", raw, flags=re.IGNORECASE)
    if not m:
        m = re.fullmatch(r"москва\s*,\s*(.+)", raw, flags=re.IGNORECASE)
    if m:
        station = normalize_metro_station_name(m.group(1))
        return build_moscow_location(station)
    return raw[:1].upper() + raw[1:] if raw else raw


def _line_emoji(color: str) -> str:
    mapping = {
        "#f91f22": "🔴",
        "#05ff16": "🟢",
        "#2075b1": "🔵",
        "#52d2f4": "🔹",
        "#75573e": "🟤",
        "#f6990e": "🟠",
        "#821c71": "🟣",
        "#ffcd1e": "🟡",
        "#ffd84d": "🟨",
        "#adacac": "⚫",
        "#b1d332": "🟩",
        "#82d4c7": "🩵",
        "#9fb7c7": "🩶",
        "#de64b7": "🌸",
        "#497561": "💚",
    }
    return mapping.get(str(color).lower(), "🚇")
