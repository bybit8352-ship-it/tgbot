import asyncio
import logging
import os
import random
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

# Проверка и загрузка шрифта
if not FONT_PATH.exists():
    print("Скачиваем шрифт...")
    try:
        urllib.request.urlretrieve(
            "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.tar.bz2",
            "dejavu.tar.bz2"
        )
        with tarfile.open("dejavu.tar.bz2", "r:bz2") as tar:
            tar.extractall(filter="data")  # Безопасная распаковка
        os.rename("dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf", "DejaVuSans.ttf")
        os.system("rm -rf dejavu-fonts-ttf-2.37 dejavu.tar.bz2")
    except Exception as e:
        print(f"Ошибка при загрузке шрифта: {e}")

# Проверка и загрузка герба
if not GERB_PATH.exists():
    print("Скачиваем герб...")
    try:
        urllib.request.urlretrieve(
            "https://i.ibb.co/wFwx99F8/Group-118.png",
            "gerb.png"
        )
    except Exception as e:
        print(f"Ошибка при загрузке герба: {e}")

# Регистрация шрифта
try:
    pdfmetrics.registerFont(TTFont("DejaVuSans", "DejaVuSans.ttf"))
except Exception as e:
    print(f"Ошибка регистрации шрифта: {e}")

# ==================== НАСТРОЙКИ ====================
API_TOKEN = "8529858406:AAE2vJZf-N8GwK3bO2UMwBa0xZ--P7r_HcU"
GROUP_ID = -1003344596004
TRUSTED_USERS = {777000, 123456789}

from zoneinfo import ZoneInfo
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

FLOOD_CONTROL = {}
VERIFICATION_CODES = {}
REPLY_TRACKER = {}
TEMP_DIR = Path("/tmp/temp_media")  # Временная директория для Render.com
TEMP_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

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

# ======================= СТАРТ =======================
@dp.message(Command("start"))
async def cmd
@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Подать заявление")]], 
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "Привет!\nОфициальный бот Управления делами президента школы.",
        reply_markup=kb
    )


# ======================= ПОДАТЬ ЗАЯВЛЕНИЕ =======================
@dp.message(F.text == "Подать заявление")
async def start_application(message: Message, state: FSMContext):
    if not await check_flood(message):
        return
    uid = message.from_user.id

    if uid in TRUSTED_USERS:
        await state.update_data(
            verified=False,
            user_id=uid,
            username=message.from_user.username or "не указан"
        )
        await state.set_state(ApplicationStates.waiting_for_name)
        await message.answer(
            "1. Напиши своё <b>ФИО полностью</b>:",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    if await is_suspicious_client(message):
        kb = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="Отправить номер", request_contact=True)]
            ],
            resize_keyboard=True
        )
        await message.answer(
            "Обнаружен неофициальный клиент.\nТребуется подтверждение номера.",
            reply_markup=kb
        )
        await state.set_state(VerificationStates.waiting_for_phone)
        return

    await state.update_data(
        verified=False,
        user_id=uid,
        username=message.from_user.username or "не указан"
    )
    await state.set_state(ApplicationStates.waiting_for_name)
    await message.answer(
        "1. Напиши своё <b>ФИО полностью</b>:",
        reply_markup=ReplyKeyboardRemove()
    )

# ======================= ВЕРИФИКАЦИЯ =======================
@dp.message(VerificationStates.waiting_for_phone, F.contact)
async def get_phone(message: Message, state: FSMContext):
    if message.contact.user_id != message.from_user.id:
        await message.answer("Это не твой номер!")
        return
    code = random.randint(1000, 9999)
    VERIFICATION_CODES[message.from_user.id] = {
        "code": code,
        "expires": datetime.now() + timedelta(minutes=5)
    }
    await bot.send_message(
        message.from_user.id,
        f"Код подтверждения: <b>{code}</b>",
        parse_mode=ParseMode.HTML
    )
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
    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Отправить без фото/видео")],
            [types.KeyboardButton(text="Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("5. Прикрепи фото/видео или нажми кнопку:", reply_markup=kb)

@dp.message(ApplicationStates.waiting_for_media, F.text == "Отправить без фото/видео")
async def skip_media(message: Message, state: FSMContext):
    await finalize_application(message, state)

@dp.message(ApplicationStates.waiting_for_media, F.photo | F.video)
async def get_media(message: Message, state: FSMContext):
    file = message.photo[-1] if message.photo else message.video
    if message.video and file.file_size > 50 * 1024 * 1024:
        await message.answer("Видео больше 50 МБ — нельзя.")
        return
    f = await bot.get_file(file.file_id)
    ext = ".jpg" if message.photo else ".mp4"
    path = TEMP_DIR / f"{message.from_user.id}_{file.file_id[-10:]}{ext}"
    await bot.download_file(f.file_path, path)
    await state.update_data(media=str(path))
    kb = types.ReplyKeyboardMarkup
        keyboard=[[types.KeyboardButton(text="Отправить заявку")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Медиа получено! Нажми кнопку ниже:", reply_markup=kb)

@dp.message(ApplicationStates.waiting_for_media, F.text == "Отправить заявку")
async def send_with_media(message: Message, state: FSMContext):
    await finalize_application(message, state)


# ======================= ФИНАЛИЗАЦИЯ =======================
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

        # Создаём PDF
        pdf_buffer = create_official_pdf(
            title="ОФИЦИАЛЬНЫЙ ОТВЕТ",
            lines=lines,
            photo_path=data.get("media")
        )

        # Отправляем в группу
        try:
            pdf_file = FSInputFile(pdf_buffer, filename="заявление.pdf")
            await bot.send_document(
                chat_id=GROUP_ID,
                document=pdf_file,
                caption=(
                    f"<b>Заявление от:</b> {data['name']}\n"
                    f"<b>Класс:</b> {data['class_name']}\n"
                    f"<b>Тема:</b> {data['theme']}\n"
                    f"<b>Дата:</b> {datetime.now(MOSCOW_TZ):%d.%m.%Y %H:%M}"
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logging.error(f"Ошибка отправки в группу: {e}")
            await message.answer("Ошибка отправки заявки. Попробуйте позже.")
            return

        # Ответ пользователю
        await message.answer(
            "Ваша заявка отправлена!\n\n"
            "Номер вашей заявки: <code>УДП-{message.from_user.id}-{int(datetime.now().timestamp())}</code>\n\n"
            "Мы рассмотрим её в ближайшее время.",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove()
        )

        # Очищаем состояние
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка при финализации заявки: {e}")
        await message.answer("Произошла ошибка. Начните заново.")
        await state.clear()


# ======================= ОБРАБОТКА ОТМЕНЫ =======================
@dp.message(F.text == "Отмена")
async def cancel_application(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Заявка отменена.", reply_markup=ReplyKeyboardRemove())


# ======================= ЗАПУСК БОТА =======================
async def main():
    print("Бот УДП полностью готов и запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

