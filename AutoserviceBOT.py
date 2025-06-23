import logging
from datetime import datetime, timedelta
import sqlite3
from dotenv import load_dotenv
load_dotenv(dotenv_path="TELEGRAM_BOT_TOKEN.env")
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler
from telegram.ext import ContextTypes
import re
from telegram import ReplyKeyboardRemove
import os
import hashlib
import smtplib
from email.mime.text import MIMEText

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы для состояний ConversationHandler
CHOOSING_SERVICE, GETTING_CONTACT, CHOOSING_DATE, CHOOSING_TIME, DESCRIPTION, CONFIRM_BOOKING, GETTING_EMAIL_AFTER_CONFIRM = range(7)
ADMIN_AUTH, ADMIN_ACTION, VIEW_BOOKINGS, ADD_SERVICE, REMOVE_SERVICE = range(5, 10)

# Константы для типов обратных вызовов
SERVICE_CALLBACK = "service_"
DATE_CALLBACK = "date_"
TIME_CALLBACK = "time_"
CONFIRM_CALLBACK = "confirm_"
ADMIN_CALLBACK = "admin_"
DELETE_BOOKING = "delete_"
ADMIN_CHAT_ID = 966063834 
SMTP_SERVER = 'smtp.yandex.ru'
SMTP_PORT = 465
EMAIL_SENDER = 'SpectrumTradeBot@yandex.ru'
EMAIL_PASSWORD = 'dkhcateivqohiuhg'
EMAIL_RECEIVER = 'spectrumtradebot@gmail.com'


    # Инициализация базы данных
def init_db():
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    
    # Создание таблицы услуг
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        price REAL
    )
    ''')
    
    # Создание таблицы бронирований
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        user_name TEXT,
        phone_number TEXT,
        service_id INTEGER,
        service_name TEXT,
        date TEXT,
        time TEXT,
        description TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (service_id) REFERENCES services (id)
    )
    ''')
    
    # Создание таблицы администраторов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        username TEXT,
        password TEXT,
        is_superadmin INTEGER DEFAULT 0
    )
    ''')
    #Создание таблицы отзывов
    cursor.execute('''
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    user_name TEXT,
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')
    
    
    # Проверяем наличие услуг в таблице, если пусто - добавляем базовые услуги
    cursor.execute("SELECT COUNT(*) FROM services")
    if cursor.fetchone()[0] == 0:
        services = [
            ("Замена масла", "Замена масла и масляного фильтра", 1500.0),
            ("Диагностика подвески", "Полная диагностика ходовой части", 1000.0),
            ("Замена тормозных колодок", "Замена передних/задних тормозных колодок", 2000.0),
            ("Компьютерная диагностика", "Диагностика электронных систем автомобиля", 1800.0),
            ("Шиномонтаж", "Сезонная замена шин", 2500.0),
            ("Развал-схождение", "Регулировка углов установки колес", 3000.0),
        ]
        cursor.executemany("INSERT INTO services (name, description, price) VALUES (?, ?, ?)", services)
    
    # Проверяем наличие админов, если нет - добавляем суперадмина
    cursor.execute("SELECT COUNT(*) FROM admins")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO admins (user_id, username, password, is_superadmin) VALUES (?, ?, ?, ?)", 
                       (123456789, "admin", "admin123", 1))
    
    conn.commit()
    conn.close()

# Получение списка услуг из БД
def get_services():
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, price FROM services")
    services = cursor.fetchall()
    conn.close()
    return services

def hash_phone_number(phone: str) -> str:
    return hashlib.sha256(phone.encode('utf-8')).hexdigest()

# Получение информации об услуге по ID
def get_service_by_id(service_id):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, price FROM services WHERE id = ?", (service_id,))
    service = cursor.fetchone()
    conn.close()
    return service

# Добавление новой услуги
def add_service(name, description, price):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO services (name, description, price) VALUES (?, ?, ?)", 
                   (name, description, price))
    conn.commit()
    conn.close()

# Удаление услуги по ID
def remove_service(service_id):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM services WHERE id = ?", (service_id,))
    conn.commit()
    conn.close()

# Создание новой записи (бронирования)
def create_booking(user_id, user_name, phone_number, service_id, service_name, date, time, description):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()

    # Хэшируем номер
    hashed_phone = hash_phone_number(phone_number)

    cursor.execute('''
    INSERT INTO bookings (user_id, user_name, phone_number, service_id, service_name, date, time, description)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, user_name, hashed_phone, service_id, service_name, date, time, description))
    
    booking_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return booking_id

# Получение бронирований пользователя
def get_user_bookings(user_id):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT id, service_name, date, time, status FROM bookings
    WHERE user_id = ? AND status != 'cancelled' ORDER BY date, time
''', (user_id,))
    bookings = cursor.fetchall()
    conn.close()
    return bookings

# Получение всех активных бронирований
def get_all_bookings():
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_name, phone_number, service_name, date, time, description, status
        FROM bookings
        WHERE status != 'cancelled'
        ORDER BY date, time
    ''')
    bookings = cursor.fetchall()
    conn.close()
    return bookings

# Удаление бронирования
def cancel_booking_by_id(booking_id):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()

# Проверка, является ли пользователь администратором
def is_admin(user_id):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_superadmin FROM admins WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Проверка пароля администратора
def check_admin_password(user_id, password):
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_superadmin FROM admins WHERE user_id = ? AND password = ?", (user_id, password))
    result = cursor.fetchone()
    conn.close()
    return result is not None

#Система отзывов
LEAVING_FEEDBACK = 20  # Добавим новое состояние

async def feedback_command(update: Update, context: CallbackContext) -> int:
    cancel_keyboard = ReplyKeyboardMarkup(
        [["❌ Отмена"]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

    await update.message.reply_text(
        "Пожалуйста, напишите ваш отзыв или нажмите ❌ Отмена, чтобы выйти.",
        reply_markup=cancel_keyboard
    )
    return LEAVING_FEEDBACK

async def save_feedback(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    text = update.message.text.strip()

    if text == "❌ Отмена":
        return await cancel(update, context)

    # Сохраняем отзыв
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO feedback (user_id, user_name, message) VALUES (?, ?, ?)",
                   (user.id, user.first_name, text))
    conn.commit()
    conn.close()

    main_menu = ReplyKeyboardMarkup(
        [
            ["📅 Записаться", "📝 Мои записи"],
            ["ℹ️ О сервисе", "❓ Помощь"],
            ["💬 Оставить отзыв"]
        ],
        resize_keyboard=True
    )

    await update.message.reply_text(
        "Спасибо за ваш отзыв!\nВозвращаем вас в главное меню.",
        reply_markup=main_menu
    )

    return ConversationHandler.END

# Команда /start
async def start(update: Update, context: CallbackContext) -> None:
    user_name = update.effective_user.first_name

    keyboard = [
    ["📅 Записаться", "📝 Мои записи"],
    ["ℹ️ О сервисе", "❓ Помощь"],
    ["💬 Оставить отзыв"]
]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    text = (
        f"Здравствуйте, {user_name}! Добро пожаловать в бот автосервиса.\n\n"
        f"Что вы хотите сделать?\n\n"
        f"Используйте команду 📅 Записаться для записи на обслуживание\n"
        f"Используйте команду 📝 Мои записи для просмотра ваших записей\n"
        f"Используйте команду ℹ️ О сервисе для получения информации об автосервисе\n"
        f"Используйте команду ❓ Помощь для получения справки\n"
    )

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)

        def get_main_menu(is_admin=False):
            keyboard = [
                ["📅 Записаться", "📝 Мои записи"],
                ["ℹ️ О сервисе", "❓ Помощь"],
                ["💬 Оставить отзыв"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        

# Команда /help
async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "Этот бот позволяет записаться на обслуживание в наш автосервис.\n\n"
        "Доступные команды:\n"
        "/start - Перезапустить бота\n"
        "📅 Записаться - Записаться на обслуживание\n"
        "📝 Мои записи - Посмотреть ваши текущие записи\n"
        "ℹ️ О сервисе - Информация об автосервисе\n"
        "❓ Помощь - Показать эту справку"
    )

# Команда /info
async def info_command(update: Update, context: CallbackContext) -> None:
    keyboard = [
        ["🏠 Главное меню", "💭 Отзывы пользователей"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "🔧 *Автосервис \"Спектр-трейд\"* 🔧\n\n"
        "*Адрес:* г.Омск ул. 2-я Барнаульская, 63А\n"
        "*Телефон:* +7 983 626-83-65\n"
        "*Часы работы:* Пн-Пт с 8:00 до 20:00 Сб с 8:00 до 14:00\n\n"
        "*Наши услуги:*\n"
        "- Диагностика и ремонт\n"
        "- Техническое обслуживание\n"
        "- Шиномонтаж\n"
        "- Кузовной ремонт\n"
        "- Замена масла и фильтров\n"
        "- Компьютерная диагностика\n\n"
        "Записаться на обслуживание можно с помощью команды 📅 Записаться",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# Начало процесса записи на обслуживание
async def book_command(update: Update, context: CallbackContext) -> int:
    # Очистка данных
    if 'booking_data' in context.user_data:
        context.user_data.pop('booking_data')

    context.user_data['booking_data'] = {}

    services = get_services()
    keyboard = []

    for service_id, name, description, price in services:
        keyboard.append([InlineKeyboardButton(f"{name} - {price:.2f} руб.", callback_data=f"{SERVICE_CALLBACK}{service_id}")])
    inline_markup = InlineKeyboardMarkup(keyboard)

    # Создаём reply-кнопку отмены
    cancel_reply_markup = ReplyKeyboardMarkup(
        [["❌ Отменить оформление заявки"]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

    # Показываем кнопку отмены и скрываем старое меню
    await update.message.reply_text(
        "Вы начали оформление заявки. В любой момент нажмите кнопку ниже, чтобы отменить.",
        reply_markup=cancel_reply_markup
    )

    await update.message.reply_text(
        "Какую услугу вы хотите заказать?",
        reply_markup=inline_markup
    )

    return CHOOSING_SERVICE
# Обработка выбора услуги
async def service_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Запись отменена. Используйте 📅 Записаться для начала новой записи.")
        return ConversationHandler.END
    
    service_id = int(query.data.replace(SERVICE_CALLBACK, ""))
    service = get_service_by_id(service_id)
    
    if not service:
        await query.edit_message_text("Услуга не найдена. Начните заново с команды 📅 Записаться.")
        return ConversationHandler.END
    
    # Сохраняем выбранную услугу в данных пользователя
    context.user_data['booking_data']['service_id'] = service_id
    context.user_data['booking_data']['service_name'] = service[1]
    context.user_data['booking_data']['service_price'] = service[3]
    
    # Запрашиваем контактные данные
    await query.edit_message_text(
        f"Вы выбрали: {service[1]} ({service[3]:.2f} руб.)\n\n"
        f"Пожалуйста, поделитесь своим номером телефона, нажав на кнопку ниже или введите его вручную в формате +7XXXXXXXXXX."
    )
    
    keyboard = [[InlineKeyboardButton("Отмена", callback_data="cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    contact_keyboard = ReplyKeyboardMarkup(
    [
        [
            {"text": "Поделиться контактом", "request_contact": True},
            "❌ Отменить оформление заявки"
        ]
    ],
    one_time_keyboard=True,
    resize_keyboard=True
    )

    
    await query.message.reply_text(
        "Или нажмите, чтобы поделиться контактом",
        reply_markup=contact_keyboard
    )
    
    return GETTING_CONTACT

def send_email(phone_number, user_name, service_name, date, time):
    body = (
        f"📞 Новая заявка\n\n"
        f"Имя: {user_name}\n"
        f"Телефон: {phone_number}\n"
        f"Услуга: {service_name}\n"
        f"Дата: {date}\n"
        f"Время: {time}"
    )

    msg = MIMEText(body)
    msg['Subject'] = 'Заявка от клиента'
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Email отправлен.")
    except Exception as e:
        print("Ошибка отправки email:", e)

def send_email_to_client(email, user_name, service_name, date, time):
    body = (
        f"Здравствуйте, {user_name}!\n\n"
        f"Вы записались на услугу: {service_name}\n"
        f"Дата: {date}\n"
        f"Время: {time}\n\n"
        f"Спасибо, что выбрали наш автосервис!"
    )

    msg = MIMEText(body)
    msg['Subject'] = 'Подтверждение вашей записи'
    msg['From'] = EMAIL_SENDER
    msg['To'] = email

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email отправлен клиенту: {email}")
    except Exception as e:
        print(f"Ошибка при отправке email клиенту: {e}")

# Обработка получения контакта
async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    if update.message.contact:
        phone_number = update.message.contact.phone_number
    else:
        phone_number = update.message.text.strip()

        # Проверка формата номера
        if not re.fullmatch(r"\+7\d{10}", phone_number):
            await update.message.reply_text(
                "Номер введён в неверном формате. Пожалуйста, введите номер в формате +7XXXXXXXXXX."
            )
            return GETTING_CONTACT

    logger.info("Контакт от пользователя %s: %s", user.first_name, phone_number)

    context.user_data['booking_data']['phone_number'] = phone_number
    context.user_data['booking_data']['user_name'] = user.first_name

    # Получаем данные из контекста
    booking = context.user_data['booking_data']

    if update.message:
        await update.message.reply_text(
        "Спасибо, информация сохранена.",
        reply_markup=ReplyKeyboardRemove()
    )

    # Генерация выбора даты
    keyboard = []
    today = datetime.now().date()
    added = 0
    i = 1  # начинаем с завтрашнего дня

# Добавим максимум 7 рабочих дней (Пн–Сб), исключая воскресенье (6)
    while added < 7:
        booking_date = today + timedelta(days=i)
        weekday = booking_date.weekday()  # 0 - Пн, ..., 6 - Вс

        if weekday < 6:  # Пн–Сб
            date_str = booking_date.strftime("%d.%m.%Y")
            date_callback = booking_date.strftime("%Y-%m-%d")
            keyboard.append([InlineKeyboardButton(date_str, callback_data=f"{DATE_CALLBACK}{date_callback}")])
            added += 1  # ← только когда день подходит — добавляем

        i += 1  # ← обязательно двигаем к следующему дню


    reply_markup = InlineKeyboardMarkup(keyboard)

    cancel_reply_markup = ReplyKeyboardMarkup(
    [["❌ Отменить оформление заявки"]],
    resize_keyboard=True,
    one_time_keyboard=False
)

    await update.message.reply_text(
    "Выберите дату для записи:",
    reply_markup=reply_markup
)

    await update.message.reply_text(
    "Для отмены вы можете воспользоваться кнопкой ниже.",
    reply_markup=cancel_reply_markup  # Показываем Reply-кнопку
)

    return CHOOSING_DATE

    

# Обработка выбора даты
async def date_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Запись отменена. Используйте 📅 Записаться для начала новой записи.")
        return ConversationHandler.END

    # Извлекаем дату из callback_data
    date_str = query.data.replace(DATE_CALLBACK, "")
    context.user_data['booking_data']['date'] = date_str

    # Получаем уже занятые слоты из БД
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT time FROM bookings WHERE date = ? AND status != 'cancelled'", (date_str,))
    taken_times = {row[0] for row in cursor.fetchall()}
    conn.close()

    # Генерируем доступное время
    weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()

    interval = 1  # Общий интервал (для всех дней)

    if weekday == 5:  # Суббота
        start_hour = 8
        end_hour = 14
    else:
        start_hour = 8
        end_hour = 19

    keyboard = []
    for hour in range(start_hour, end_hour, interval):
        time_str = f"{hour:02d}:00"
        if time_str in taken_times:
            continue  # пропускаем занятые
        keyboard.append([InlineKeyboardButton(time_str, callback_data=f"{TIME_CALLBACK}{time_str}")])

    if not keyboard:
        keyboard.append([InlineKeyboardButton("❌ Нет доступного времени", callback_data="cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"Выбрана дата: {date_str}\nТеперь выберите время:",
        reply_markup=reply_markup
    )

    # Покажем кнопку "Отменить оформление заявки"
    
    reply_markup=ReplyKeyboardMarkup(
            [["❌ Отменить оформление заявки"]],
            resize_keyboard=True,
            one_time_keyboard=False
        )

    return CHOOSING_TIME

# Обработка выбора времени
async def time_choice(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Запись отменена. Используйте 📅 Записаться для начала новой записи.")
        return ConversationHandler.END
    
    # Извлекаем время из callback_data
    time_str = query.data.replace(TIME_CALLBACK, "")
    context.user_data['booking_data']['time'] = time_str
    
    from telegram import ReplyKeyboardMarkup

    reply_markup = ReplyKeyboardMarkup(
    [["❌ Отменить оформление заявки"]],
    resize_keyboard=True,
    one_time_keyboard=False
)
    reply_markup = ReplyKeyboardMarkup(
    [["Пропустить", "❌ Отменить оформление заявки"]],
    resize_keyboard=True,
    one_time_keyboard=False
)

    await query.edit_message_text(
    f"Выбрано время: {time_str}"
)

    await query.message.reply_text(
    "Пожалуйста, опишите проблему или нажмите 'Пропустить':",
    reply_markup=reply_markup
)
    
    return DESCRIPTION

# Пропуск описания
async def skip_description(update: Update, context: CallbackContext) -> int:
    context.user_data['booking_data']['description'] = "Не указано"
    
    return await show_booking_confirmation(update, context)

# Получение описания
async def get_description(update: Update, context: CallbackContext) -> int:
    description = update.message.text
    context.user_data['booking_data']['description'] = description
    
    return await show_booking_confirmation(update, context)

# Показать подтверждение бронирования
async def show_booking_confirmation(update: Update, context: CallbackContext) -> int:
    booking_data = context.user_data['booking_data']
    
    confirmation_text = (
        "*Подтверждение записи*\n\n"
        f"*Услуга:* {booking_data['service_name']}\n"
        f"*Стоимость:* {booking_data['service_price']:.2f} руб.\n"
        f"*Дата:* {booking_data['date']}\n"
        f"*Время:* {booking_data['time']}\n"
        f"*Телефон:* {booking_data['phone_number']}\n"
        f"*Описание:* {booking_data['description']}\n\n"
        "Пожалуйста, проверьте и подтвердите запись."
    )
    
    keyboard = [
    [InlineKeyboardButton("✅ Подтвердить", callback_data=f"{CONFIRM_CALLBACK}yes")],
]
    reply_markup = ReplyKeyboardMarkup(
    [["✅ Подтвердить", "❌ Отменить оформление заявки"]],
    resize_keyboard=True,
    one_time_keyboard=False
)
    
    if update.message:
        await update.message.reply_text(
        confirmation_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    else:
        await update.callback_query.message.reply_text(
        confirmation_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return CONFIRM_BOOKING

# Обработка подтверждения бронирования
async def confirm_booking(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    choice = query.data.replace(CONFIRM_CALLBACK, "")
    
    if choice == "no":
        await query.edit_message_text("Запись отменена. Используйте 📅 Записаться для начала новой записи.")
        return ConversationHandler.END
    
    # Создаем запись в базе данных
    booking_data = context.user_data['booking_data']
    booking_id = create_booking(
        update.effective_user.id,
        booking_data['user_name'],
        booking_data['phone_number'],
        booking_data['service_id'],
        booking_data['service_name'],
        booking_data['date'],
        booking_data['time'],
        booking_data['description']
    )
    
    main_menu = ReplyKeyboardMarkup(
    [["🏠 Главное меню"]],
    resize_keyboard=True,
    one_time_keyboard=False
)
    booking_data = context.user_data.get("booking_data")
    booking_id = create_booking(booking_data)
    
    await query.edit_message_text(
    f"✅ Запись успешно создана!\n\n"
    f"Ваш номер записи: *{booking_id}*\n\n"
    f"Вы записаны на {booking_data['service_name']} {booking_data['date']} в {booking_data['time']}.\n\n"
    f"Мы свяжемся с вами по номеру {booking_data['phone_number']} для подтверждения.\n\n"
    f"Используйте «📝 Мои записи» для просмотра ваших записей.",
    parse_mode='Markdown'
)

# Отдельным сообщением отправляем клавиатуру
    await query.message.reply_text("Для возврата в главное меню нажмите кнопку 🏠 Главное меню ", reply_markup=main_menu)
    
    # Очищаем данные бронирования
    if 'booking_data' in context.user_data:
        context.user_data.pop('booking_data')
    
    return ConversationHandler.END

# Просмотр записей пользователя
async def my_bookings(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    bookings = get_user_bookings(user_id)
    
    if not bookings:
        await update.message.reply_text("У вас нет активных записей. Используйте 📅 Записаться для создания новой записи.")
        return
    
    message = "*Ваши записи:*\n\n"
    
    for booking_id, service_name, date, time, status in bookings:
        status_text = "✅ Подтверждена" if status == "confirmed" else "⏳ Ожидает подтверждения"
        
        message += (
            f"*Запись #{booking_id}*\n"
            f"Услуга: {service_name}\n"
            f"Дата и время: {date} в {time}\n"
            f"Статус: {status_text}\n\n"
        )
    
    keyboard = [[InlineKeyboardButton("Отменить запись", callback_data="cancel_booking")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# Обработка отмены записи
async def cancel_booking_request(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    bookings = get_user_bookings(user_id)
    
    if not bookings:
        await query.edit_message_text("У вас нет активных записей.")
        return

    message = "*Выберите запись для отмены:*\n\n"
    keyboard = []

    for booking_id, service_name, date, time, status in bookings:
        status_text = "✅ Подтверждена" if status == "confirmed" else "⏳ Ожидает подтверждения"
        message += (
            f"*Запись #{booking_id}*\n"
            f"Услуга: {service_name}\n"
            f"Дата и время: {date} в {time}\n"
            f"Статус: {status_text}\n\n"
        )
        keyboard.append([
            InlineKeyboardButton(
                f"🗑 Отменить запись #{booking_id}",
                callback_data=f"{DELETE_BOOKING}{booking_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_booking_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# Удаление записи пользователя
async def delete_user_booking(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_booking_menu":
        await query.edit_message_text("❌ Возврат отменён.")
        return

    booking_id = int(query.data.replace(DELETE_BOOKING, ""))

    # Получаем данные об удаляемой записи
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT user_name, phone_number, service_name, date, time, description
    FROM bookings WHERE id = ?
    ''', (booking_id,))
    booking = cursor.fetchone()
    conn.close()

    if booking:
        user_name, phone, service, date, time, description = booking

    # Уведомление по email
        try:
            body = (
                f"❌ Заявка отменена\n\n"
                f"Имя: {user_name}\n"
                f"Услуга: {service}\n"
                f"Дата: {date}\n"
                f"Время: {time}\n"
                f"Описание: {description}"
            )

            msg = MIMEText(body)
            msg['Subject'] = f'❌ Отмена заявки #{booking_id}'
            msg['From'] = EMAIL_SENDER
            msg['To'] = EMAIL_RECEIVER

            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
            server.quit()
            print(f"Email об отмене отправлен админу.")
        except Exception as e:
            print(f"Ошибка при отправке email админу: {e}")

    # Уведомление в Telegram
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=(
            f"❌ *Заявка отменена*\n\n"
            f"*Имя:* {user_name}\n"
            f"*Услуга:* {service}\n"
            f"*Дата:* {date}\n"
            f"*Время:* {time}\n"
            f"*Описание:* {description}"
        ),
        parse_mode='Markdown'
    )

    cancel_booking_by_id(booking_id)

    # Повторно получаем обновлённый список записей
    user_id = update.effective_user.id
    bookings = get_user_bookings(user_id)

    if not bookings:
        await query.edit_message_text("Запись удалена. У вас больше нет активных записей.")
        return

    message = f"✅ Запись #{booking_id} удалена.\n\n*Ваши оставшиеся записи:*\n\n"
    keyboard = []

    for bid, service_name, date, time, status in bookings:
        status_text = "✅ Подтверждена" if status == "confirmed" else "⏳ Ожидает подтверждения"
        message += (
            f"*Запись #{bid}*\n"
            f"Услуга: {service_name}\n"
            f"Дата и время: {date} в {time}\n"
            f"Статус: {status_text}\n\n"
        )
        keyboard.append([
            InlineKeyboardButton(f"🗑 Отменить запись #{bid}", callback_data=f"{DELETE_BOOKING}{bid}")
        ])

    # Добавим кнопку "❌ Отмена"
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_booking_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# Вход в панель администратора
async def admin_command(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    
    # Проверяем, является ли пользователь администратором
    if not is_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к панели администратора.")
        return ConversationHandler.END

    await show_admin_panel(update, context)
    return ConversationHandler.END

# Аутентификация администратора
async def admin_auth(update: Update, context: CallbackContext) -> int:
    password = update.message.text
    user_id = update.effective_user.id
    
    if check_admin_password(user_id, password):
        await show_admin_panel(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text("Неверный пароль. Доступ запрещен.")
        return ConversationHandler.END

# Показать панель администратора
async def show_admin_panel(update: Update, context: CallbackContext) -> None:
    keyboard = [
    [InlineKeyboardButton("Посмотреть записи", callback_data=f"{ADMIN_CALLBACK}view_bookings")],
    [InlineKeyboardButton("Управление услугами", callback_data=f"{ADMIN_CALLBACK}manage_services")],
    [InlineKeyboardButton("Отзывы пользователей", callback_data=f"{ADMIN_CALLBACK}feedbacks")],  # ← добавь это
    [InlineKeyboardButton("Выход", callback_data=f"{ADMIN_CALLBACK}exit")]
]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(
            "Панель администратора\n\nВыберите действие:",
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.edit_message_text(
            "Панель администратора\n\nВыберите действие:",
            reply_markup=reply_markup
        )

# Обработка действий администратора
async def admin_actions(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    action = query.data.replace(ADMIN_CALLBACK, "")
    
    if action == "exit":
        await query.edit_message_text("Выход из панели администратора.")
        return
    
    elif action == "view_bookings":
        bookings = get_all_bookings()
        
        if not bookings:
            await query.edit_message_text(
                "Нет активных записей.\n\n"
                "Вернуться в [панель администратора](/admin)"
            )
            return
        
        message = "*Все записи:*\n\n"
        
        for booking_id, user_name, phone, service, date, time, description, status in bookings:
            status_text = "✅ Подтверждена" if status == "confirmed" else "⏳ Ожидает подтверждения"
            
            message += (
                f"*Запись #{booking_id}*\n"
                f"Клиент: {user_name}\n"
                f"Услуга: {service}\n"
                f"Дата и время: {date} в {time}\n"
                f"Описание: {description}\n"
                f"Статус: {status_text}\n\n"
            )
        
        keyboard = [[InlineKeyboardButton("Назад", callback_data=f"{ADMIN_CALLBACK}back_to_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif action == "manage_services":
        services = get_services()
        
        message = "*Управление услугами:*\n\n"
        
        keyboard = [
            [InlineKeyboardButton("Добавить услугу", callback_data=f"{ADMIN_CALLBACK}add_service")],
            [InlineKeyboardButton("Назад", callback_data=f"{ADMIN_CALLBACK}back_to_panel")]
        ]
        
        for service_id, name, description, price in services:
            message += f"*{name}* - {price:.2f} руб.\n{description}\n\n"
            keyboard.insert(-1, [InlineKeyboardButton(f"Удалить '{name}'", callback_data=f"{ADMIN_CALLBACK}remove_service_{service_id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif action == "back_to_panel":
        await show_admin_panel(update, context)
    
    elif action.startswith("remove_service_"):
        service_id = int(action.replace("remove_service_", ""))
        remove_service(service_id)
        
        await query.edit_message_text(
            f"Услуга #{service_id} успешно удалена.\n\n"
            f"Нажмите /admin для возврата в панель администратора."
        )
        
    elif action == "add_service":
        context.user_data['admin_action'] = 'add_service'
        await query.edit_message_text(
            "Добавление новой услуги.\n\n"
            "Введите название услуги, описание и цену в формате:\n"
            "Название | Описание | Цена\n\n"
            "Например:\n"
            "Замена колодок | Замена тормозных колодок, все включено | 2500"
        )
        # Переходим в состояние добавления услуги
        return ADD_SERVICE
    
    elif action == "feedbacks":
        conn = sqlite3.connect('autoservice_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_name, message, created_at FROM feedback ORDER BY created_at DESC LIMIT 10")
        feedbacks = cursor.fetchall()
        conn.close()

        if not feedbacks:
            await query.edit_message_text("Нет отзывов.")
            return

        message = "*Отзывы пользователей:*\n\n"
        keyboard = []

        for index, (fid, user, msg, created) in enumerate(feedbacks, start=1):
            message += f"*{index}. 👤 {user}* ({created.split()[0]}):\n{msg}\n\n"
            keyboard.append([
                InlineKeyboardButton(f"🗑 Удалить отзыв {index}", callback_data=f"{ADMIN_CALLBACK}delete_feedback_{fid}")
            ])

        keyboard.append([InlineKeyboardButton("Назад", callback_data=f"{ADMIN_CALLBACK}back_to_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

    elif action.startswith("delete_feedback_"):
        feedback_id = int(action.replace("delete_feedback_", ""))
        conn = sqlite3.connect('autoservice_bot.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        conn.commit()

        cursor.execute("SELECT id, user_name, message, created_at FROM feedback ORDER BY created_at DESC LIMIT 10")
        feedbacks = cursor.fetchall()
        conn.close()

        if not feedbacks:
            await query.edit_message_text("Все отзывы удалены.")
            return

        message = "✅ Отзыв удалён.\n\n*Обновлённый список отзывов:*\n\n"
        keyboard = []

        for index, (fid, user, msg, created) in enumerate(feedbacks, start=1):
            message += f"*{index}. 👤 {user}* ({created.split()[0]}):\n{msg}\n\n"
            keyboard.append([
                InlineKeyboardButton(f"🗑 Удалить отзыв {index}", callback_data=f"{ADMIN_CALLBACK}delete_feedback_{fid}")
            ])

        keyboard.append([InlineKeyboardButton("Назад", callback_data=f"{ADMIN_CALLBACK}back_to_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')


# Обработка добавления новой услуги
async def add_service_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    parts = text.split('|')
    
    if len(parts) != 3:
        await update.message.reply_text(
            "Неверный формат. Пожалуйста, используйте формат:\n"
            "Название | Описание | Цена\n\n"
            "Например:\n"
            "Замена колодок | Замена тормозных колодок, все включено | 2500"
        )
        return ADD_SERVICE
    
    name = parts[0].strip()
    description = parts[1].strip()
    
    try:
        price = float(parts[2].strip())
    except ValueError:
        await update.message.reply_text("Цена должна быть числом. Попробуйте снова.")
        return ADD_SERVICE
    
    # Добавляем услугу в БД
    add_service(name, description, price)
    
    await update.message.reply_text(
        f"✅ Услуга '{name}' успешно добавлена!\n\n"
        f"Нажмите /admin для возврата в панель администратора."
    )
    
    return ConversationHandler.END

# Отмена операции
async def cancel(update: Update, context: CallbackContext) -> int:
    user_name = update.effective_user.first_name

    # Скрываем текущую клавиатуру
    await update.message.reply_text(
        "Операция отменена.",
        reply_markup=ReplyKeyboardRemove()
    )

    # Клавиатура главного меню
    main_menu = ReplyKeyboardMarkup(
        [
           ["📅 Записаться", "📝 Мои записи"],
    ["ℹ️ О сервисе", "❓ Помощь"],
    ["💬 Оставить отзыв"]
        ],
        resize_keyboard=True
    )

    # Сообщение с предложением действия
    await update.message.reply_text(
        f"{user_name}, что вы хотите сделать дальше?",
        reply_markup=main_menu
    )

    return ConversationHandler.END

async def confirm_booking_text(update: Update, context: CallbackContext) -> int:
    # Создаём "фейковый" callback_query с нужными данными
    class DummyQuery:
        def __init__(self, update):
            self.data = f"{CONFIRM_CALLBACK}yes"
            self.message = update.message
            self.from_user = update.effective_user

        async def answer(self):
            pass

        async def edit_message_text(self, *args, **kwargs):
            await self.message.reply_text(*args, **kwargs)

    dummy_query = DummyQuery(update)
    return await confirm_booking_from_text(dummy_query, update, context)

async def confirm_booking_from_text(query, update: Update, context: CallbackContext) -> int:
    await query.answer()

    choice = query.data.replace(CONFIRM_CALLBACK, "")

    if choice == "no":
        await query.edit_message_text("Запись отменена. Используйте 📅 Записаться для начала новой записи.")
        return ConversationHandler.END

    booking_data = context.user_data['booking_data']
    booking_id = create_booking(
        update.effective_user.id,
        booking_data['user_name'],
        booking_data['phone_number'],
        booking_data['service_id'],
        booking_data['service_name'],
        booking_data['date'],
        booking_data['time'],
        booking_data['description']
    )
    if 'email' in booking_data:
        send_email_to_client(
        booking_data['email'],
        booking_data['user_name'],
        booking_data['service_name'],
        booking_data['date'],
        booking_data['time']
    )

    main_menu = ReplyKeyboardMarkup(
    [["🏠 Главное меню"]],
    resize_keyboard=True,
    one_time_keyboard=False
)

    await query.edit_message_text(
    f"✅ Запись успешно создана!\n\n"
    f"Ваш номер записи: *{booking_id}*\n\n"
    f"Вы записаны на {booking_data['service_name']} {booking_data['date']} в {booking_data['time']}.\n\n"
    f"Мы свяжемся с вами по номеру {booking_data['phone_number']} для подтверждения.\n\n"
    f"Используйте 📝 Мои записи для просмотра ваших записей.",
    parse_mode='Markdown'
)

    await query.message.reply_text("Для возврата в главное меню нажмите кнопку 🏠 Главное меню", reply_markup=main_menu)

    # Уведомление администратора
    send_email(
        booking_data['phone_number'],
        booking_data['user_name'],
        booking_data['service_name'],
        booking_data['date'],
        booking_data['time']
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=(
            f"📞 Новая подтверждённая заявка\n\n"
            f"Имя: {booking_data['user_name']}\n"
            f"Телефон: {booking_data['phone_number']}\n"
            f"Услуга: {booking_data['service_name']}\n"
            f"Дата: {booking_data['date']}\n"
            f"Время: {booking_data['time']}\n"
            f"Описание: {booking_data['description']}"
        )
    )

    # Предложение пользователю ввести email
    keyboard = ReplyKeyboardMarkup(
        [["Нет, вернуться в 🏠Главное меню"]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await query.message.reply_text(
        "Если хотите получить копию вашей записи на электронную почту, пожалуйста введите email в формате example@mail.ru.\n\n"
        "Или нажмите кнопку ниже, чтобы вернуться в главное меню.",
        reply_markup=keyboard
    )

    # Сохраняем данные бронирования
    context.user_data['last_booking'] = {
        'user_name': booking_data['user_name'],
        'service_name': booking_data['service_name'],
        'date': booking_data['date'],
        'time': booking_data['time']
    }

    # Очищаем booking_data
    if 'booking_data' in context.user_data:
        context.user_data.pop('booking_data')

    return GETTING_EMAIL_AFTER_CONFIRM

async def handle_email_or_skip(update: Update, context: CallbackContext) -> int:
    text = update.message.text.strip()

    if text.lower() == "нет, вернуться в главное меню":
        await update.message.reply_text(
            "Хорошо! Возвращаю вас в главное меню.✅",
            reply_markup=ReplyKeyboardMarkup(
                [["📅 Записаться", "📝 Мои записи"], ["ℹ️ О сервисе", "❓ Помощь"]],
                resize_keyboard=True
            )
        )
        return ConversationHandler.END

    # Проверка email
    if not re.fullmatch(r"[^@ \t\r\n]+@[^@ \t\r\n]+\.[^@ \t\r\n]+", text):
        await update.message.reply_text(
            "Некорректный email. Попробуйте снова или нажмите кнопку ниже для возврата.",
            reply_markup=ReplyKeyboardMarkup(
                [["Нет, вернуться в главное меню"]],
                resize_keyboard=True
            )
        )
        return GETTING_EMAIL_AFTER_CONFIRM

    # Отправка письма
    booking = context.user_data.get('last_booking')
    if booking:
        send_email_to_client(
            text,
            booking['user_name'],
            booking['service_name'],
            booking['date'],
            booking['time']
        )

    await update.message.reply_text(
        "✅ Копия вашей записи отправлена на почту.",
        reply_markup=ReplyKeyboardMarkup(
            [["📅 Записаться", "📝 Мои записи"], ["ℹ️ О сервисе", "❓ Помощь"]],
            resize_keyboard=True
        )
    )

    context.user_data.pop('last_booking', None)
    return ConversationHandler.END

def send_email_to_client(email, user_name, service_name, date, time):
    body = (
        f"Здравствуйте, {user_name}!\n\n"
        f"Вы записались на услугу: {service_name}\n"
        f"Дата: {date}\n"
        f"Время: {time}\n\n"
        f"Если вы хотите изменить или отменить запись — свяжитесь с нами.\n\n"
        f"Спасибо, что выбрали наш автосервис!"
    )

    msg = MIMEText(body)
    msg['Subject'] = 'Подтверждение вашей записи'
    msg['From'] = EMAIL_SENDER
    msg['To'] = email

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email отправлен клиенту: {email}")
    except Exception as e:
        print(f"Ошибка при отправке email клиенту: {e}")

async def show_feedbacks(update: Update, context: CallbackContext) -> None:
    conn = sqlite3.connect('autoservice_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_name, message, created_at FROM feedback ORDER BY created_at DESC LIMIT 5")
    feedbacks = cursor.fetchall()
    conn.close()

    if not feedbacks:
        await update.message.reply_text("Пока нет отзывов от пользователей.")
        return

    text = "*Последние отзывы:*\n\n"
    for name, message, created_at in feedbacks:
        formatted_time = created_at.split(" ")[0]
        text += f"👤 *{name}* ({formatted_time}):\n{message}\n\n"

    keyboard = [["🏠 Главное меню"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    

# Запуск бота
def main() -> None:

    print("Реальный путь к используемой БД:", os.path.abspath("autoservice_bot.db"))
    # Инициализация базы данных
    init_db()
    
    # Получение токена из переменной окружения или напрямую
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # Создание приложения
    application = Application.builder().token(token).build()
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("mybookings", my_bookings))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📝 Мои записи$"), my_bookings))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex("^ℹ️ О сервисе$"), info_command))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex("^❓ Помощь$"), help_command))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_menu$"))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex("^💭 Отзывы пользователей$"), show_feedbacks))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🏠 Главное меню$"), start))
    fallbacks=[
    CommandHandler("cancel", cancel),
    MessageHandler(filters.TEXT & filters.Regex("^❌ Отменить оформление заявки$"), cancel)
    ],
    
    # Обработчик отзывов
    feedback_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.TEXT & filters.Regex("^💬 Оставить отзыв$"), feedback_command)],
    states={
        LEAVING_FEEDBACK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, save_feedback)
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        MessageHandler(filters.TEXT & filters.Regex("^❌ Отменить оформление заявки$"), cancel),
    ],
)
    application.add_handler(feedback_conv_handler)
    
    # Обработчик для записи на обслуживание
    booking_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.TEXT & filters.Regex("^📅 Записаться$"), book_command)],
    states={
        CHOOSING_SERVICE: [CallbackQueryHandler(service_choice)],
        GETTING_CONTACT: [
            MessageHandler(filters.CONTACT, get_contact),
            MessageHandler(filters.TEXT & filters.Regex("^❌ Отменить оформление заявки$"), cancel),
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Отменить оформление заявки$"), get_contact),
        ],
        CHOOSING_DATE: [CallbackQueryHandler(date_choice)],
        CHOOSING_TIME: [CallbackQueryHandler(time_choice)],
        DESCRIPTION: [
            MessageHandler(filters.TEXT & filters.Regex("^❌ Отменить оформление заявки$"), cancel),
            MessageHandler(filters.TEXT & filters.Regex("^Пропустить$"), skip_description),
            CommandHandler("skip", skip_description),
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_description),
        ],
        
        CONFIRM_BOOKING: [
            CallbackQueryHandler(confirm_booking),
            MessageHandler(filters.TEXT & filters.Regex("^✅ Подтвердить$"), confirm_booking_text),
            MessageHandler(filters.TEXT & filters.Regex("^❌ Отменить оформление заявки$"), cancel),
        ],
        GETTING_EMAIL_AFTER_CONFIRM: [
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_or_skip)
],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        MessageHandler(filters.TEXT & filters.Regex("^❌ Отменить оформление заявки$"), cancel),
    ]
)
    application.add_handler(booking_conv_handler)

    
    # Обработчик для панели администратора
    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("secretcommand", admin_command)],
        states={
            ADD_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_service_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(admin_conv_handler)
    
    # Обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(cancel_booking_request, pattern="^cancel_booking$"))
    application.add_handler(CallbackQueryHandler(delete_user_booking, pattern=f"^{DELETE_BOOKING}"))
    application.add_handler(CallbackQueryHandler(admin_actions, pattern=f"^{ADMIN_CALLBACK}"))
    application.add_handler(CallbackQueryHandler(start, pattern="^cancel$"))
    
    
    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()