ICONS = {
    "Аренда": "🏠",
    "Вакансия": "🧑‍💼",
    "Услуги": "🛠",
    "Купля / Продажа": "🛒"
}

FIELDS = {
    "Аренда": [
        ("object", "🏢 Объект"),
        ("price", "💲 Цена"),
        ("location", "📍 Локация"),
        ("area", "🏠 Площадь"),
        ("terms", "📑 Условия"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ],
    "Вакансия": [
        ("position", "👤 Должность"),
        ("salary", "💰 Зарплата"),
        ("location", "📍 Локация"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ],
    "Услуги": [
        ("service", "🔧 Услуга"),
        ("price", "💲 Цена/Условия"),
        ("location", "📍 Локация"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ],
    "Купля / Продажа": [
        ("item", "📦 Товар / Объект"),
        ("price", "💲 Цена"),
        ("location", "📍 Локация"),
        ("state", "📃 Состояние"),
        ("contacts", "📞 Контакты"),
        ("description", "📝 Описание"),
    ]
}

def build_post(category: str, data: dict) -> str:
    lines = [f"{ICONS.get(category, '')} <b>{category}</b>:", ""]
    for key, label in FIELDS.get(category, []):
        value = data.get(key)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)

def generate_tags(category: str, data: dict) -> str:
    tags = ["#FindexHub"]
    if category == "Аренда":
        if data.get("object"): tags.append(f"#{data['object'].replace(' ', '')}")
        if data.get("location"): tags.append(f"#{data['location'].replace(' ', '')}")
    elif category == "Вакансия":
        if data.get("position"): tags.append(f"#{data['position'].replace(' ', '')}")
        if data.get("location"): tags.append(f"#{data['location'].replace(' ', '')}")
    elif category == "Услуги":
        if data.get("service"): tags.append(f"#{data['service'].replace(' ', '')}")
        if data.get("location"): tags.append(f"#{data['location'].replace(' ', '')}")
    elif category == "Купля / Продажа":
        if data.get("item") or data.get("object"):
            tags.append(f"#{(data.get('item') or data.get('object')).replace(' ', '')}")
        if data.get("location"): tags.append(f"#{data['location'].replace(' ', '')}")
    return " ".join(tags)

def parse_field_from_reason(reason, category: str) -> str:
    first_sentence = reason.strip().split('.', 1)[0].strip()
    first_word = first_sentence.split()[0].lower() if first_sentence else ""
    mapping = {}
    for key, label in FIELDS[category]:
        label_clean = label.split(" ", 1)[-1].split(":")[0].strip().lower()
        mapping[label_clean] = key
    if first_word in mapping:
        return mapping[first_word]
    for label_clean, key in mapping.items():
        if first_sentence.lower().startswith(label_clean):
            return key
    return None

def user_profile_link(user):
    if hasattr(user, "username") and user.username:
        return f'<a href="https://t.me/{user.username}">@{user.username}</a>'
    else:
        return f'<a href="tg://user?id={user.id}">{getattr(user, "full_name", "Пользователь")}</a>'