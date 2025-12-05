import asyncio
import logging
import os
import random
import urllib.request
import tarfile
import urllib.request
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove, ContentType, Contact, BufferedInputFile, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# PDF + герб + шрифт
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO


# ==================== АВТОЗАГРУЗКА ШРИФТА И ГЕРБА ====================
FONT_PATH = Path("DejaVuSans.ttf")
GERB_PATH = Path("gerb.png")
PORT = int(os.environ.get("PORT", 5000))


if not FONT_PATH.exists():
    print("Скачиваем шрифт...")
    urllib.request.urlretrieve("https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2", "dejavu.tar.bz2")
    with tarfile.open("dejavu.tar.bz2", "r:bz2") as tar:
        tar.extractall()
    os.rename("dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf", "DejaVuSans.ttf")
    os.system("rm -rf dejavu-fonts-ttf-2.37 dejavu.tar.bz2")

if not GERB_PATH.exists():
    print("Скачиваем герб...")
    urllib.request.urlretrieve("https://i.ibb.co/wFwx99F8/Group-118.png", "gerb.png")

pdfmetrics.registerFont(TTFont("DejaVuSans", "DejaVuSans.ttf"))

# ==================== НАСТРОЙКИ ====================
API_TOKEN = "8529858406:AAE2vJZf-N8GwK3bO2UMwBa0xZ--P7r_HcU"
GROUP_ID = -1003344596004
TRUSTED_USERS = {777000, 123456789}

from zoneinfo import ZoneInfo
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

FLOOD_CONTROL = {}
VERIFICATION_CODES = {}
REPLY_TRACKER = {}
TEMP_DIR = Path("temp_media")
TEMP_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class ApplicationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_class = State()
    waiting_for_theme = State()
    waiting_for_description = State()
    waiting_for_media = State()

class VerificationStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()


async def is_suspicious_client(message: Message) -> bool:
    user = message.from_user
    if getattr(user, "is_fake", False) or getattr(user, "is_scam", False):
        return True
    raw = getattr(message, "_raw_update", None)
    if raw and any(x in str(raw).lower() for x in ["ayugram", "nekogram", "nicegram", "exteragram", "AyuGram"]):
        return True
    return False


async def check_flood(message: Message) -> bool:
    uid = message.from_user.id
    now = datetime.now().timestamp()
    last = FLOOD_CONTROL.get(uid, 0)
    if now - last < 30:
        await message.answer(f"Подожди ещё {int(30 - (now - last))} сек.")
        return False
    FLOOD_CONTROL[uid] = now
    return True


def wrap_text(text, c, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = cur + w + " "
        if c.stringWidth(test, "DejaVuSans", 12) < max_w:
            cur = test
        else:
            lines.append(cur.strip())
            cur = w + " "
    if cur: lines.append(cur.strip())
    return lines


def create_official_pdf(title: str, lines: list, photo_path=None) -> BytesIO:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Герб в верхнем левом углу
    try:
        c.drawImage("gerb.png", 40, height - 200, width=120, height=120, preserveAspectRatio=True)
    except Exception as e:
        print(f"Ошибка загрузки герба: {e}")
    
    # Заголовок справа от герба
    y_position = height - 140
    c.setFont("DejaVuSans", 18)
    c.drawString(180, y_position, title)
    
    # Основной текст справа от герба
    y_position -= 40
    c.setFont("DejaVuSans", 12)
    
    for line in lines:
        if y_position < 200:  # Оставляем место для фотографии
            c.showPage()
            y_position = height - 50
        
        if line.startswith("!!BOLD!!"):
            c.setFont("DejaVuSans", 14)
            line = line.replace("!!BOLD!!", "")
        else:
            c.setFont("DejaVuSans", 12)
        
        # Разбиваем длинные строки и выводим текст начиная с позиции справа от герба
        wrapped_lines = wrap_text(line, c, width - 220)  # Оставляем место для герба
        for wrapped_line in wrapped_lines:
            c.drawString(180, y_position, wrapped_line)
            y_position -= 18
    
    # Добавление фотографии в нижнюю правую часть
    if photo_path and os.path.exists(photo_path):
        try:
            photo_y = max(200, y_position - 350)  # Размещаем фотографию в нижней части
            photo_height = min(300, y_position - 150)  # Ограничиваем высоту фотографии
            c.drawImage(photo_path, width - 200, photo_y - photo_height, width=180, height=photo_height, preserveAspectRatio=True)
        except Exception as e:
            print(f"Ошибка добавления фотографии: {e}")
    
    # Нижняя подпись
    c.setFont("DejaVuSans", 10)
    c.drawRightString(width - 50, 30, f"Документ сформирован: {datetime.now(MOSCOW_TZ):%d.%m.%Y %H:%M} МСК")
    
    c.save()
    buffer.seek(0)
    return buffer


# ======================= СТАРТ =======================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="Подать заявление")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Привет!\nОфициальный бот Управления делами президента школы.", reply_markup=kb)


# ======================= ПОДАТЬ ЗАЯВЛЕНИЕ =======================
@dp.message(F.text == "Подать заявление")
async def start_application(message: Message, state: FSMContext):
    if not await check_flood(message): return
    uid = message.from_user.id

    if uid in TRUSTED_USERS:
        await state.update_data(verified=False, user_id=uid, username=message.from_user.username or "не указан")
        await state.set_state(ApplicationStates.waiting_for_name)
        await message.answer("1. Напиши своё <b>ФИО полностью</b>:", reply_markup=ReplyKeyboardRemove())
        return

    if await is_suspicious_client(message):
        kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="Отправить номер", request_contact=True)]], resize_keyboard=True)
        await message.answer("Обнаружен неофициальный клиент.\nТребуется подтверждение номера.", reply_markup=kb)
        await state.set_state(VerificationStates.waiting_for_phone)
        return

    await state.update_data(verified=False, user_id=uid, username=message.from_user.username or "не указан")
    await state.set_state(ApplicationStates.waiting_for_name)
    await message.answer("1. Напиши своё <b>ФИО полностью</b>:", reply_markup=ReplyKeyboardRemove())


# ======================= ВЕРИФИКАЦИЯ =======================
@dp.message(VerificationStates.waiting_for_phone, F.contact)
async def get_phone(message: Message, state: FSMContext):
    if message.contact.user_id != message.from_user.id:
        await message.answer("Это не твой номер!")
        return
    code = random.randint(1000, 9999)
    VERIFICATION_CODES[message.from_user.id] = {"code": code, "expires": datetime.now() + timedelta(minutes=5)}
    await bot.send_message(message.from_user.id, f"Код подтверждения: <b>{code}</b>", parse_mode=ParseMode.HTML)
    await message.answer("Код отправлен в ЛС! Введи его сюда:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(VerificationStates.waiting_for_code)

@dp.message(VerificationStates.waiting_for_code)
async def verify_code(message: Message, state: FSMContext):
    data = VERIFICATION_CODES.get(message.from_user.id)
    if not data or datetime.now() > data["expires"]:
        await message.answer("Код устарел. Начни заново.")
        await state.clear()
        return
    if message.text.strip() != str(data["code"]):
        await message.answer("Неверный код.")
        return
    del VERIFICATION_CODES[message.from_user.id]
    await state.update_data(verified=True, user_id=message.from_user.id, username=message.from_user.username or "не указан")
    await state.set_state(ApplicationStates.waiting_for_name)
    await message.answer("Верификация пройдена!\n\n1. Напиши своё <b>ФИО полностью</b>:")


# ======================= ШАГИ ЗАЯВКИ =======================
@dp.message(ApplicationStates.waiting_for_name)
async def get_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name.split()) < 2:
        await message.answer("Укажи полное ФИО.")
        return
    await state.update_data(name=name)
    await state.set_state(ApplicationStates.waiting_for_class)
    await message.answer("2. Класс (например 10 «А»):")

@dp.message(ApplicationStates.waiting_for_class)
async def get_class(message: Message, state: FSMContext):
    await state.update_data(class_name=message.text.strip())
    await state.set_state(ApplicationStates.waiting_for_theme)
    await message.answer("3. Тема обращения (коротко):")

@dp.message(ApplicationStates.waiting_for_theme)
async def get_theme(message: Message, state: FSMContext):
    await state.update_data(theme=message.text.strip())
    await state.set_state(ApplicationStates.waiting_for_description)
    await message.answer("4. Подробно опиши проблему:")

@dp.message(ApplicationStates.waiting_for_description)
async def get_description(message: Message, state: FSMContext):
    if message.content_type not in [ContentType.TEXT, ContentType.PHOTO, ContentType.VIDEO]:
        await message.answer("Пришли текстом.")
        return
    await state.update_data(description=(message.text or message.caption or "—").strip())
    await state.set_state(ApplicationStates.waiting_for_media)
    kb = types.ReplyKeyboardMarkup(keyboard=[
        [types.KeyboardButton(text="Отправить без фото/видео")],
        [types.KeyboardButton(text="Отмена")]
    ], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("5. Прикрепи фото/видео или нажми кнопку:", reply_markup=kb)

@dp.message(ApplicationStates.waiting_for_media, F.text == "Отправить без фото/видео")
async def skip_media(message: Message, state: FSMContext):
    await finalize_application(message, state)

@dp.message(ApplicationStates.waiting_for_media, F.photo | F.video)
async def get_media(message: Message, state: FSMContext):
    file = message.photo[-1] if message.photo else message.video
    if message.video and file.file_size > 50*1024*1024:
        await message.answer("Видео больше 50 МБ — нельзя.")
        return
    f = await bot.get_file(file.file_id)
    ext = ".jpg" if message.photo else ".mp4"
    path = TEMP_DIR / f"{message.from_user.id}_{file.file_id[-10:]}{ext}"
    await bot.download_file(f.file_path, path)
    await state.update_data(media=str(path))
    kb = types.ReplyKeyboardMarkup(keyboard=[[types.KeyboardButton(text="Отправить заявку")]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Медиа получено! Нажми кнопку ниже:", reply_markup=kb)

@dp.message(ApplicationStates.waiting_for_media, F.text == "Отправить заявку")
async def send_with_media(message: Message, state: FSMContext):
    await finalize_application(message, state)

# ======================= ФИНАЛИЗАЦИЯ =======================
def create_official_pdf(title: str, lines: list, photo_path=None) -> BytesIO:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Герб по центру в верхней части
    try:
        gerb_width = 140
        gerb_x = (width - gerb_width) / 2
        c.drawImage("gerb.png", gerb_x, height - 220, width=gerb_width, height=140, preserveAspectRatio=True)
    except Exception as e:
        print(f"Ошибка загрузки герба: {e}")
    
    # Заголовок "ОФИЦИАЛЬНЫЙ ОТВЕТ" по центру
    y_position = height - 280
    c.setFont("DejaVuSans", 22)
    title_width = c.stringWidth(title, "DejaVuSans", 22)
    c.drawString((width - title_width) / 2, y_position, title)
    y_position -= 60
    
    # Основной текст выравнивается слева
    c.setFont("DejaVuSans", 12)
    
    for line in lines:
        if y_position < 300:
            c.showPage()
            y_position = height - 50
        
        # Если строка начинается с !!BOLD!!, делаем её жирным
        if line.startswith("!!BOLD!!"):
            c.setFont("DejaVuSans", 14)
            line = line.replace("!!BOLD!!", "")
        
        # Разбиваем длинные строки и выводим текст слева с отступом 60
        wrapped_lines = wrap_text(line, c, width - 120)
        for wrapped_line in wrapped_lines:
            if y_position < 300:
                c.showPage()
                y_position = height - 50
            c.drawString(60, y_position, wrapped_line)
            y_position -= 18
    
    # Дата в нижнем правом углу
    c.setFont("DejaVuSans", 12)
    date_text = f"Документ сформирован: {datetime.now(MOSCOW_TZ):%d.%m.%Y %H:%M} МСК"
    c.drawRightString(width - 60, 40, date_text)
    
    c.save()
    buffer.seek(0)
    return buffer

# Определите функцию finalize_application ДО обработчиков, которые её вызывают

async def finalize_application(message: Message, state: FSMContext):
    """Завершает процесс создания и отправки заявки"""
    try:
        data = await state.get_data()
        
        # Проверяем наличие обязательных данных
        required_fields = ['name', 'class_name', 'theme', 'description']
        for field in required_fields:
            if field not in data:
                await message.answer("Ошибка: не все данные заполнены. Начните заново.")
                await state.clear()
                return
        
        # Формируем текст заявки
        lines = [
            f"ФИО: {data['name']}",
            f"Класс: {data['class_name']}",
            f"Тема: {data['theme']}",
            "Описание:",
            data['description']
        ]
        
        if data.get('verified', False):
            lines.append("Пользователь прошел верификацию по коду.")
        
        lines.extend([
            "",
            f"Идентификатор пользователя: {data['user_id']}",
            f"Username: {data.get('username', 'не указан')}",
        ])
        
        # Создаем PDF без фотографии
        pdf_buffer = create_official_pdf("ОФИЦИАЛЬНОЕ ЗАЯВЛЕНИЕ", lines)
        
        # Отправляем заявку в группу только как PDF
        filename = f"Заявка_{data['name'].replace(' ', '*')}*{datetime.now(MOSCOW_TZ):%d%m%Y_%H%M}.pdf"
        sent_message = await bot.send_document(
            GROUP_ID,
            BufferedInputFile(pdf_buffer.getvalue(), filename=filename)
        )
        
        # Сохраняем информацию для отслеживания ответа
        REPLY_TRACKER[sent_message.message_id] = message.from_user.id
        
        # Если есть медиафайл, отправляем его в группу отдельно после PDF
        if 'media' in data:
            media_path_str = data['media']
            if media_path_str and os.path.exists(media_path_str):
                try:
                    # Проверяем расширение файла через os.path.splitext
                    file_extension = os.path.splitext(media_path_str)[1].lower()
                    
                    if file_extension == '.jpg' or file_extension == '.jpeg':
                        await bot.send_photo(GROUP_ID, FSInputFile(media_path_str))
                    elif file_extension == '.mp4':
                        await bot.send_video(GROUP_ID, FSInputFile(media_path_str))
                    else:
                        # Если расширение неизвестно, отправляем как документ
                        await bot.send_document(GROUP_ID, FSInputFile(media_path_str))
                except Exception as e:
                    logging.error(f"Ошибка отправки медиа в группу: {e}")
        
        # Уведомляем пользователя об успешной отправке
        await message.answer(
            "✅ Ваша заявка успешно отправлена в Управление делами президента.\n\n"
            "Ответ будет отправлен вам в личные сообщения после рассмотрения."
        )
        
        await state.clear()
        
    except Exception as e:
        logging.error(f"Ошибка при финализации заявки: {e}")
        await message.answer("Произошла ошибка при создании заявки. Попробуйте начать заново.")

# Обработчик ответов из группы
@dp.message(F.chat.id == GROUP_ID, F.reply_to_message)
async def reply_from_group(message: Message):
    if message.reply_to_message.from_user.id != (await bot.get_me()).id:
        return
    
    user_id = REPLY_TRACKER.get(message.reply_to_message.message_id)
    if not user_id:
        return

    try:
        text = message.text or message.caption or "Ответ на вашу заявку."
        admin = message.from_user.full_name

        lines = [
            "",
            "Уважаемый ученик!",
            "",
            "По вашей заявке:",
            "",
            text,
            "",
            
            f"Ответил: {admin} - Управление делами президента школы",
        ]

        # Создаем и отправляем PDF только с текстом, выровненным слева
        pdf_buffer = create_official_pdf("ОФИЦИАЛЬНЫЙ ОТВЕТ", lines)
        filename = f"Ответ_УДПШ_{datetime.now(MOSCOW_TZ):%d%m%Y_%H%M}.pdf"
        await bot.send_document(user_id, BufferedInputFile(pdf_buffer.getvalue(), filename=filename))

        # Если есть фотография, отправляем её отдельно после PDF
        if message.photo:
            await bot.send_photo(user_id, message.photo[-1].file_id)

        await message.answer("✅ Ответ отправлен пользователю.")

    except Exception as e:
        logging.error(f"Ошибка при отправке ответа: {e}")
        await message.answer("❌ Не удалось отправить ответ пользователю.")

@dp.message(ApplicationStates.waiting_for_media, F.text == "Отправить без фото/видео")
async def skip_media(message: Message, state: FSMContext):
    await finalize_application(message, state)

@dp.message(ApplicationStates.waiting_for_media, F.text == "Отправить заявку")
async def send_with_media(message: Message, state: FSMContext):
    await finalize_application(message, state)



# Также добавляем обработчик для отмены в любом состоянии
@dp.message(F.text == "Отмена")
async def cancel_anytime(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.", reply_markup=ReplyKeyboardRemove())

# Добавляем обработчик для обработки любых сообщений в состоянии ожидания медиа
@dp.message(ApplicationStates.waiting_for_media)
async def handle_media_or_text(message: Message, state: FSMContext):
    if message.text and message.text not in ["Отправить без фото/видео", "Отправить заявку", "Отмена"]:
        await message.answer(
            "Пожалуйста, отправьте фото/видео или используйте кнопку 'Отправить без фото/видео'."
        )
        return

# ======================= ОТВЕТ В PDF С ГЕРБОМ =======================
@dp.message(F.chat.id == GROUP_ID, F.reply_to_message)
async def reply_from_group(message: Message):
    if message.reply_to_message.from_user.id != (await bot.get_me()).id:
        return
    
    user_id = REPLY_TRACKER.get(message.reply_to_message.message_id)
    if not user_id:
        return
    
    text = message.text or message.caption or "Без текста"
    admin = message.from_user.full_name
    
    # Формируем текст ответа
    lines = [
        "ОФИЦИАЛЬНЫЙ ОТВЕТ",
        f"Дата: {datetime.now(MOSCOW_TZ):%d.%m.%Y}",
        "",
        "Уважаемый ученик!",
        "",
        "По вашей заявке:",
        "",
        text,
        "",
        "— Управление делами президента школы",
        f"Ответил: {admin}"
    ]
    
    try:
        # Создаем PDF БЕЗ фотографии
        pdf = create_official_pdf("ОФИЦИАЛЬНЫЙ ОТВЕТ УДПШ", lines)
        
        filename = f"Ответ_УДПШ_{datetime.now(MOSCOW_TZ):%d%m%Y_%H%M}.pdf"
        await bot.send_document(user_id, BufferedInputFile(pdf.getvalue(), filename=filename))
        
        # Если есть медиафайлы, отправляем их отдельно как сообщения
        if message.photo:
            await bot.send_photo(user_id, message.photo[-1])
        elif message.video:
            await bot.send_video(user_id, message.video)
        elif message.document:
            await bot.send_document(user_id, message.document)
            
        await message.answer("✅ Ответ отправлен пользователю в виде официального документа.")
        
    except Exception as e:
        logging.error(f"Ошибка при отправке ответа: {e}")
        await message.answer("❌ Не удалось отправить ответ пользователю.")

@dp.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())

if __name__ == '__main__':
    # Указываем порт при запуске
    from aiogram import executor
    executor.start_webhook(
        dispatcher=dp,
        webhook_path="/",
        skip_updates=True,
        on_startup=on_startup,
        port=PORT
    )
    
async def main():
    print("Бот УДП полностью готов и запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
