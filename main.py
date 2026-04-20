import asyncio
import os
import re
from datetime import datetime, timedelta
from telethon import TelegramClient
from telegram import Update, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ─── Настройки ────────────────────────────────────────────────────────────────

def load_env_file(path: str = ".env") -> None:
    """Простой загрузчик .env без внешних зависимостей."""
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name, "")
    if not value.strip():
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


load_env_file()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
CITY = os.getenv("CITY", "Красный Луч")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Локальные чаты — фильтр по городу не нужен
CHATS_LOCAL = env_list("CHATS_LOCAL", [
    "luch24",
    "Kr_Luch_PROvse",
    "Kr_Luch_PROvse_Chat",
    "krluch_novosti",
    "vesti_KrasniyLuch"
])

# Региональные чаты — фильтруем только сообщения с упоминанием города
CHATS_REGIONAL = env_list("CHATS_REGIONAL", [
    "luganskallnews",
    "prilet_lugansk"
])

CHATS_TO_WATCH = CHATS_LOCAL + CHATS_REGIONAL

CITY_ALIASES = env_list("CITY_ALIASES", [
    "красный луч",
    "кр. луч",
    "кр.луч",
])

EVENT_ALIASES = {
    "авария":      ["авария", "аварии", "чп"],
    "дтп":         ["дтп", "столкновение", "наезд"],
    "происшествие":["происшествие", "инцидент"],
    "отключение":  ["отключение", "без света", "нет света", "обесточ"],
    "пожар":       ["пожар", "горит", "возгорание", "задымление"],
    "взрыв":       ["взрыв", "хлопок", "детонация"],
    "бпла":        ["бпла", "дрон", "беспилотник"],
}

KEYWORDS = env_list("KEYWORDS", ["авария", "дтп", "происшествие", "отключение", "пожар", "взрыв", "бпла"])
EVENT_PATTERNS = {
    event: re.compile("|".join(re.escape(alias) for alias in aliases), re.IGNORECASE)
    for event, aliases in EVENT_ALIASES.items()
    if event in KEYWORDS
}

# Кнопки меню → ключевые слова для поиска
BUTTON_MAP = {
    "🔥 пожар":      "пожар",
    "💥 взрыв":      "взрыв",
    "🚗 дтп":        "дтп",
    "⚡ отключение": "отключение",
    "🚨 авария":     "авария",
    "✈️ бпла":       "бпла",
    "📋 сегодня":    "__today__",
    "❓ помощь":     "__help__",
}

userbot = TelegramClient("observer_session", API_ID, API_HASH)


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def message_matches_city(text: str) -> bool:
    t = text.lower()
    return any(alias in t for alias in CITY_ALIASES)


def message_matches_keywords(text: str) -> str | None:
    """Возвращает событие из KEYWORDS по синонимам или None."""
    for event in KEYWORDS:
        pattern = EVENT_PATTERNS.get(event)
        if pattern and pattern.search(text):
            return event
    return None


def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🔥 Пожар"),      KeyboardButton("💥 Взрыв")],
        [KeyboardButton("🚗 ДТП"),        KeyboardButton("⚡ Отключение")],
        [KeyboardButton("🚨 Авария"),     KeyboardButton("✈️ БПЛА")],
        [KeyboardButton("📋 Сегодня"),    KeyboardButton("❓ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


def detect_event_from_query(text: str) -> str | None:
    normalized = text.lower().strip()
    for event in KEYWORDS:
        pattern = EVENT_PATTERNS.get(event)
        if pattern and pattern.search(normalized):
            return event
    return None


def is_today_request(text: str) -> bool:
    normalized = text.lower()
    return any(phrase in normalized for phrase in ["сегодня", "за сегодня", "today"])


# ─── Поиск ────────────────────────────────────────────────────────────────────

async def _iter_chat(chat_username: str, time_limit: datetime, limit: int):
    """Генератор: отдаёт (message, msg_time) для одного чата."""
    chat = await userbot.get_entity(chat_username)
    async for message in userbot.iter_messages(chat, limit=limit):
        if not message.text:
            continue
        msg_time = message.date.replace(tzinfo=None)
        if msg_time < time_limit:
            break
        yield message, msg_time


async def live_search_in_chats(query: str, hours: int = 720, limit_per_chat: int = 1000) -> list[dict]:
    """Поиск по конкретному слову. Кнопки меню передают только ключевые слова."""
    results = []
    query_lower = query.lower()
    target_event = detect_event_from_query(query)
    time_limit = datetime.now() - timedelta(hours=hours)

    for chat_username in CHATS_LOCAL:
        try:
            async for message, msg_time in _iter_chat(chat_username, time_limit, limit_per_chat):
                message_event = message_matches_keywords(message.text)
                matches = (message_event == target_event) if target_event else (query_lower in message.text.lower())
                if matches:
                    results.append({
                        "text": message.text,
                        "chat": chat_username,
                        "date": msg_time,
                        "keyword": message_event or query_lower
                    })
        except Exception as e:
            print(f"Ошибка [{chat_username}]: {e}")

    for chat_username in CHATS_REGIONAL:
        try:
            async for message, msg_time in _iter_chat(chat_username, time_limit, limit_per_chat):
                if not message_matches_city(message.text):
                    continue
                message_event = message_matches_keywords(message.text)
                matches = (message_event == target_event) if target_event else (query_lower in message.text.lower())
                if matches:
                    results.append({
                        "text": message.text,
                        "chat": chat_username,
                        "date": msg_time,
                        "keyword": message_event or query_lower
                    })
        except Exception as e:
            print(f"Ошибка [{chat_username}]: {e}")

    results.sort(key=lambda x: x["date"], reverse=True)
    return results


async def live_search_today(hours: int = 24, limit_per_chat: int = 500) -> list[dict]:
    """Поиск за сегодня — только по KEYWORDS."""
    results = []
    time_limit = datetime.now() - timedelta(hours=hours)

    for chat_username in CHATS_LOCAL:
        try:
            async for message, msg_time in _iter_chat(chat_username, time_limit, limit_per_chat):
                kw = message_matches_keywords(message.text)
                if kw:
                    results.append({"text": message.text, "chat": chat_username, "date": msg_time, "keyword": kw})
        except Exception as e:
            print(f"Ошибка [{chat_username}]: {e}")

    for chat_username in CHATS_REGIONAL:
        try:
            async for message, msg_time in _iter_chat(chat_username, time_limit, limit_per_chat):
                if not message_matches_city(message.text):
                    continue
                kw = message_matches_keywords(message.text)
                if kw:
                    results.append({"text": message.text, "chat": chat_username, "date": msg_time, "keyword": kw})
        except Exception as e:
            print(f"Ошибка [{chat_username}]: {e}")

    results.sort(key=lambda x: x["date"], reverse=True)
    return results


# ─── Форматирование ───────────────────────────────────────────────────────────

def format_results(results: list[dict], query: str) -> list[str]:
    if not results:
        return [f"🔍 По запросу «{query}» в {CITY} ничего не найдено за последний месяц."]

    pages, current = [], f"🔍 Найдено: {len(results)} сообщений по «{query}»\n\n"

    for item in results:
        block = (
            f"📅 {item['date'].strftime('%d.%m %H:%M')} | 📢 {item['chat']}\n"
            f"{item['text'][:300].replace(chr(10), ' ')}\n"
            f"{'─' * 30}\n\n"
        )
        if len(current) + len(block) > 3900:
            pages.append(current)
            current = block
        else:
            current += block

    pages.append(current)
    return pages


def format_today_results(results: list[dict]) -> list[str]:
    if not results:
        return [f"📋 За сегодня происшествий в {CITY} не найдено."]

    pages, current = [], f"📋 Происшествия за сегодня: {len(results)} сообщений\n\n"

    for item in results:
        block = (
            f"🕐 {item['date'].strftime('%H:%M')} | 📢 {item['chat']} | 🏷 {item.get('keyword', '')}\n"
            f"{item['text'][:250].replace(chr(10), ' ')}\n"
            f"{'─' * 30}\n\n"
        )
        if len(current) + len(block) > 3900:
            pages.append(current)
            current = block
        else:
            current += block

    pages.append(current)
    return pages


# ─── Команды бота ─────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🚨 Бот-помощник {CITY}\n\n"
        f"Используйте кнопки меню или напишите любое слово для поиска.\n"
        f"Поиск ведётся по {len(CHATS_TO_WATCH)} чатам за последний месяц.",
        reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🚨 Бот-помощник {CITY}\n\n"
        f"📌 Команды:\n"
        f"/search <слово> — поиск по слову за последний месяц\n"
        f"/today — происшествия за сегодня\n"
        f"/help — эта справка\n\n"
        f"📌 Кнопки меню:\n"
        f"Нажмите категорию — бот найдёт упоминания за месяц.\n\n"
        f"📌 Свободный поиск:\n"
        f"Напишите любое слово — бот найдёт его в чатах.\n\n"
        f"📢 Чаты: {', '.join(CHATS_TO_WATCH)}",
        reply_markup=get_main_keyboard()
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Укажите слово.\nПример: /search авария",
            reply_markup=get_main_keyboard()
        )
        return

    query = ' '.join(context.args).strip()
    msg = await update.message.reply_text(f"🔍 Ищу «{query}» в {len(CHATS_TO_WATCH)} чатах...")

    try:
        results = await live_search_in_chats(query)
        pages = format_results(results, query)
        await msg.delete()
        for page in pages:
            await update.message.reply_text(page, reply_markup=get_main_keyboard())
    except Exception as e:
        try:
            await msg.edit_text(f"❌ Ошибка поиска: {e}")
        except Exception:
            await update.message.reply_text(f"❌ Ошибка поиска: {e}", reply_markup=get_main_keyboard())


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(f"🔍 Ищу происшествия за сегодня в {len(CHATS_TO_WATCH)} чатах...")

    try:
        results = await live_search_today(hours=24)
        pages = format_today_results(results)
        await msg.delete()
        for page in pages:
            await update.message.reply_text(page, reply_markup=get_main_keyboard())
    except Exception as e:
        try:
            await msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await update.message.reply_text(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    action = BUTTON_MAP.get(text.lower())

    if action == "__today__":
        await today_command(update, context)
    elif action == "__help__":
        await help_command(update, context)
    elif action:
        # Кнопка меню с ключевым словом
        context.args = [action]
        await search_command(update, context)
    elif len(text) < 3:
        await update.message.reply_text(
            "Слишком короткий запрос. Введите минимум 3 символа.",
            reply_markup=get_main_keyboard()
        )
    else:
        if is_today_request(text):
            await today_command(update, context)
            return

        detected_event = detect_event_from_query(text)
        if detected_event:
            context.args = [detected_event]
            await search_command(update, context)
            return

        # Свободный поиск
        context.args = text.split()
        await search_command(update, context)


# ─── Запуск ───────────────────────────────────────────────────────────────────

async def main():
    if not API_ID or not API_HASH or not BOT_TOKEN:
        raise ValueError(
            "Проверьте .env: должны быть заполнены API_ID, API_HASH и BOT_TOKEN."
        )

    await userbot.start()
    print("🔍 Юзербот запущен!")

    app = Application.builder().token(BOT_TOKEN).build()

    await app.bot.set_my_commands([
        BotCommand("start",  "Запустить бота"),
        BotCommand("today",  "Происшествия за сегодня"),
        BotCommand("search", "Поиск по слову"),
        BotCommand("help",   "Помощь"),
    ])

    app.add_handler(CommandHandler("start",  start_command))
    app.add_handler(CommandHandler("help",   help_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("today",  today_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    print("✅ Бот запущен! Ожидаю запросы.")
    print("=" * 50)

    await asyncio.gather(
        userbot.run_until_disconnected(),
        asyncio.Future()
    )


if __name__ == "__main__":
    asyncio.run(main())
