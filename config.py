import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram Bot ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── Владелец бота ─────────────────────────────────────────
TELEGRAM_OWNER_ID: int = int(os.getenv("TELEGRAM_OWNER_ID", "6591561847"))
OWNER_NAME: str = os.getenv("OWNER_NAME", "Рахим")

# ── Telegram Userbot и Белый список чатов ─────────────────
TELEGRAM_API_ID: str = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")
# Строковая сессия Telethon для облачного запуска (Render, Railway)
TELEGRAM_USER_SESSION: str = os.getenv("TELEGRAM_USER_SESSION", "")
# Файл динамического хранения разрешенных чатов
ALLOWED_CHATS_FILE: str = os.getenv("ALLOWED_CHATS_FILE", "allowed_chats.json")
# Начальный список разрешенных чатов через запятую
ALLOWED_CHATS_RAW: str = os.getenv("ALLOWED_CHATS", "")
ALLOWED_CHATS: list[str] = [c.strip() for c in ALLOWED_CHATS_RAW.split(",") if c.strip()]

# ── Gemini AI ─────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Google Sheets ─────────────────────────────────────────
GOOGLE_SHEETS_SPREADSHEET_ID: str = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_FILE: str = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
)
# Для развертывания в облаке (Render, Railway, Heroku и др.) можно передать содержимое JSON файлом или строкой в переменной окружения
GOOGLE_SERVICE_ACCOUNT_JSON: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
# Ваш личный email Google для выдачи доступа к новым создаваемым таблицам
USER_GOOGLE_EMAIL: str = os.getenv("USER_GOOGLE_EMAIL", "")

