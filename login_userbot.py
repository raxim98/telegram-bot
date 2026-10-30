"""One-time Telegram Account Authentication Script for Userbot.

Run this script to connect your personal Telegram account to the Userbot:
    python login_userbot.py

It will:
1. Check your TELEGRAM_API_ID and TELEGRAM_API_HASH from .env.
2. Ask for your phone number (e.g. +998901234567).
3. Send a confirmation code to your Telegram app.
4. Save the authorization permanently into 'user_session.session'.
"""

from __future__ import annotations

import asyncio
import os
import sys

from telethon import TelegramClient

from config import TELEGRAM_API_HASH, TELEGRAM_API_ID

# ── Force UTF-8 logging on Windows ────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


async def main():
    print("=" * 60)
    print("🔐 АВТОРИЗАЦИЯ ЛИЧНОГО АККАУНТА TELEGRAM ДЛЯ AI-ЮЗЕРБОТА")
    print("=" * 60)

    api_id = TELEGRAM_API_ID
    api_hash = TELEGRAM_API_HASH

    if not api_id or not api_hash:
        print("\n❌ В файле .env не указаны TELEGRAM_API_ID или TELEGRAM_API_HASH!")
        print("1. Перейдите на официальный сайт: https://my.telegram.org")
        print("2. Войдите со своим номером телефона")
        print("3. Откройте 'API development tools'")
        print("4. Создайте любое приложение (например: 'MyUserbot')")
        print("5. Скопируйте App api_id и App api_hash и добавьте их в .env:")
        print("   TELEGRAM_API_ID=12345678")
        print("   TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789\n")
        return

    print(f"Используется API ID: {api_id}")
    client = TelegramClient("user_session", int(api_id), api_hash)
    await client.start()

    me = await client.get_me()
    print("\n" + "=" * 60)
    print("🎉 УСПЕШНО АВТОРИЗОВАН!")
    print(f"• Имя: {me.first_name} {me.last_name or ''}")
    print(f"• Юзернейм: @{me.username or 'без юзернейма'}")
    print(f"• ID: {me.id}")
    print("• Сессия сохранена в: user_session.session")
    print("=" * 60)
    print("\nТеперь вы можете запустить юзербота командой:")
    print("  python userbot.py\n")


if __name__ == "__main__":
    asyncio.run(main())
