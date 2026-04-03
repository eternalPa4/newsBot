import asyncio
import sqlite3
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Данные
API_ID = 
API_HASH = ''
CITY = ""

#Чаты для просмотра ботом
CHATS_TO_WATCH = [
    "luch24",
    "Kr_Luch_PROvse",
    "luganskallnews",
    "Kr_Luch_PROvse_Chat",
    "krluch_novosti",
    "vesti_KrasniyLuch"
]

#Ключевые слова и бот-токен
KEYWORDS = ["авария", "дтп", "происшествие", "отключение", "пожар", "взрыв", "бпла"]
BOT_TOKEN = ""


def init_db():
    conn = sqlite3.connect('incidents.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT,
            message_text TEXT,
            chat_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print("База данных готова")




def save_incident(keyword, message_text, chat_name):
    conn = sqlite3.connect('incidents.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO incidents (keyword, message_text, chat_name) VALUES (?, ?, ?)',
        (keyword.lower(), message_text[:1000], chat_name)
    )
    conn.commit()
    conn.close()
    print(f"Сохранено: {keyword}")
    return True



def search_incidents(keyword, hours=24, limit=20):
    conn = sqlite3.connect('incidents.db')
    cursor = conn.cursor()
    time_ago = datetime.now() - timedelta(hours=hours)
    cursor.execute('''
        SELECT message_text, chat_name, created_at 
        FROM incidents 
        WHERE message_text LIKE ? AND created_at > ?
        ORDER BY created_at DESC 
        LIMIT ?
    ''', (f'%{keyword.lower()}%', time_ago, limit))
    results = cursor.fetchall()
    conn.close()
    return results



def get_statistics():
    conn = sqlite3.connect('incidents.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM incidents')
    total = cursor.fetchone()[0]
    today = datetime.now().date()
    cursor.execute('SELECT COUNT(*) FROM incidents WHERE DATE(created_at) = ?', (today,))
    today_count = cursor.fetchone()[0]
    cursor.execute('SELECT keyword, COUNT(*) FROM incidents GROUP BY keyword ORDER BY COUNT(*) DESC LIMIT 10')
    by_keyword = cursor.fetchall()
    conn.close()
    return total, today_count, by_keyword





userbot = TelegramClient("observer_session", API_ID, API_HASH)

@userbot.on(events.NewMessage(chats=CHATS_TO_WATCH))
async def monitor_handler(event):

    if event.out:
        print("Пропущено своё сообщение")
        return
    
    text = event.message.text
    if not text:
        return
    
    chat_name = await event.get_chat_name()
    print(f"\n[{chat_name}] {text[:100]}...")
    
    text_lower = text.lower()
    for keyword in KEYWORDS:
        if keyword.lower() in text_lower:
            save_incident(keyword, text, chat_name)
            break

async def scan_recent_messages(hours=48):
    """Сканирует последние сообщения в чатах"""
    print(f"\nСканирую сообщения за последние {hours} часов...")
    
    time_limit = datetime.now() - timedelta(hours=hours)
    found_count = 0
    
    for chat_name in CHATS_TO_WATCH:
        try:
            chat = await userbot.get_entity(chat_name)
            print(f"📢 Сканирую {chat_name}...")
            
            async for message in userbot.iter_messages(chat, limit=200):
                if not message.text:
                    continue
                
                msg_time = message.date.replace(tzinfo=None)
                if msg_time < time_limit:
                    break
                
                text_lower = message.text.lower()
                for keyword in KEYWORDS:
                    if keyword.lower() in text_lower:
                        save_incident(keyword, message.text, chat_name)
                        print(f"Найдено: {keyword} от {msg_time.strftime('%d.%m %H:%M')}")
                        found_count += 1
                        break
                        
        except Exception as e:
            print(f"Ошибка: {e}")
    
    print(f"\nНайдено {found_count} сообщений")
    return found_count

#Основные команды бота
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🚨 Бот-помощник {CITY}\n\n"
        f"Команды:\n/search слово - поиск\n/today - за сегодня\n/stats - статистика\n/scan - сканировать чаты"
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для сканирования чатов"""
    msg = await update.message.reply_text("🔍 Начинаю сканирование чатов...")
    count = await scan_recent_messages(48)
    await msg.edit_text(f"Сканирование завершено! Найдено {count} сообщений.")

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('incidents.db')
    cursor = conn.cursor()
    today_start = datetime.now().replace(hour=0, minute=0, second=0)
    cursor.execute('SELECT message_text, chat_name, created_at FROM incidents WHERE created_at >= ? ORDER BY created_at DESC LIMIT 30', (today_start,))
    incidents = cursor.fetchall()
    conn.close()
    
    if not incidents:
        await update.message.reply_text(f"За сегодня ничего не найдено.")
        return
    
    response = f"Происшествия за сегодня\n\n"
    for text, chat, date in incidents[:15]:
        response += f"[{date.strftime('%H:%M')}] {chat}\n📝 {text[:150]}\n\n"
    await update.message.reply_text(response[:4000])

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total, today_count, by_keyword = get_statistics()
    response = f"Статистика\nВсего: {total}\nЗа сегодня: {today_count}\n\nПо типам:\n"
    for kw, cnt in by_keyword:
        response += f"• {kw}: {cnt}\n"
    await update.message.reply_text(response)

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(f"Укажите слово. Доступно: {', '.join(KEYWORDS)}")
        return
    keyword = ' '.join(context.args).lower()
    
    incidents = search_incidents(keyword, hours=48, limit=15)
    if not incidents:
        await update.message.reply_text(f"Ничего не найдено по '{keyword}'")
        return
    
    response = f"🔍 Результаты: {keyword} ({len(incidents)})\n\n"
    for text, chat, date in incidents[:10]:
        response += f"[{date.strftime('%d.%m %H:%M')}] {chat}\n{text[:200]}\n\n"
    await update.message.reply_text(response[:4000])

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip().lower()
    if len(keyword) > 2:
        await search_command(update, context)


async def main():
    init_db()
    await userbot.start()
    print(f"🔍 Юзербот запущен!")
    

    await scan_recent_messages(48)
    

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    print("Бот запущен! Используйте /scan для поиска старых сообщений")
    print("=" * 50)
    
    await asyncio.gather(
        userbot.run_until_disconnected(),
        asyncio.Future()
    )

if __name__ == "__main__":
    asyncio.run(main())
