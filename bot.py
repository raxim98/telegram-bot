"""Telegram bot — entry point with robust network retry and strict permissions.

Flows:
  • Private chat:
      - Owner (Рахим): full access to all AI and Google Sheets tools.
      - Strangers: polite rejection explaining the bot is created by Рахим and obeys only him.
  • Group / Supergroup / Channel:
      - Non-whitelisted chats: completely ignored (silent).
      - Whitelisted chats:
          - Analyzes messages to see if they relate to Google Sheets or mention the bot.
          - Modifies required cells/rows in Google Sheets on behalf of the Owner.
          - Posts confirmation and table links into the chat.
  • Cloud Healthcheck HTTP server for 24/7 uptime on Render / Railway.
"""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import logging
import os
import sys
import threading

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from config import OWNER_NAME, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID
from gemini_agent import get_agent_response_async, reset_chat
from whitelist_manager import whitelist_mgr

# ── Force UTF-8 logging on Windows ────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Telegram message length limit
_TG_MAX_LEN = 4096


# ── Helper for safe sending with retries ───────────────────

async def _safe_send_message(update: Update, text: str, parse_mode: str | None = None) -> None:
    """Send message with retry on transient network errors."""
    if not update.message:
        return
    for attempt in range(1, 4):
        try:
            await update.message.reply_text(text, parse_mode=parse_mode)
            return
        except (NetworkError, TimedOut) as err:
            logger.warning("Retry %d/3 sending message due to: %s", attempt, err)
            await asyncio.sleep(1.0)
        except Exception:
            # Fallback to plain text if Markdown parsing failed
            if parse_mode:
                try:
                    await update.message.reply_text(text, parse_mode=None)
                    return
                except Exception:
                    pass
            logger.exception("Failed to send message")
            return


async def _safe_typing(update: Update) -> None:
    """Send typing action safely without crashing if network blips."""
    try:
        if update.message and update.message.chat:
            await update.message.chat.send_action("typing")
    except Exception as e:
        logger.debug("Typing action suppressed: %s", e)


# ── Handlers ──────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    # If stranger in private chat
    if chat.type == "private" and user.id != TELEGRAM_OWNER_ID:
        await _safe_send_message(
            update,
            f"👋 Здравствуйте! Я персональный ИИ-ассистент, созданный моим владельцем ({OWNER_NAME}).\n\n"
            f"Я действую исключительно от его имени и выполняю только его команды. "
            f"Посторонние запросы в личных сообщениях заблокированы.\n\n"
            f"Если вам нужно внести данные в Google Таблицу или получить доступ, пожалуйста, обратитесь напрямую к {OWNER_NAME}.",
        )
        return

    await _safe_send_message(
        update,
        f"👋 Привет, {OWNER_NAME}! Я твой персональный AI-ассистент с полным контролем над Google Таблицами и зрением (Vision).\n\n"
        f"🔥 **Основные возможности:**\n"
        f"• 🛠️ **Создание и управление таблицами** — создание с нуля, удаление, переименование, поиск по имени\n"
        f"• 🎨 **Дизайн и стили** — готовые темы, цвета, границы, сетка, шрифты, выравнивание\n"
        f"• 📊 **Данные и формулы** — добавление строк, расчет формул (=SUM, =AVERAGE), очистка\n"
        f"• 🛡️ **Работа от твоего имени в группах** — обработка запросов участников по учету данных\n"
        f"• 📤 **Отправка таблиц в чаты** — автоматические превью с кликабельными ссылками\n\n"
        f"**Команды управления:**\n"
        f"/whitelist — список разрешенных чатов\n"
        f"/allow `<id_или_юзернейм>` — добавить чат в белый список\n"
        f"/remove `<id_или_юзернейм>` — удалить чат из белого списка\n"
        f"/id — узнать ID текущего чата и пользователя\n"
        f"/reset — очистить память диалога\n"
        f"/help — подробная справка с примерами",
        parse_mode="Markdown",
    )


async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show whitelist of allowed chats (Owner only)."""
    user = update.effective_user
    if not user or user.id != TELEGRAM_OWNER_ID:
        return

    allowed = whitelist_mgr.get_all()
    if allowed:
        chats_str = "\n".join(f"• `{c}`" for c in allowed)
        text = f"🛡️ **Разрешенные чаты для работы бота ({len(allowed)}):**\n\n{chats_str}\n\nБот слушает и отвечает ТОЛЬКО в этих чатах."
    else:
        text = (
            "🛡️ **Список разрешенных чатов пока пуст!**\n\n"
            "Чтобы добавить группу или чат, используйте команду:\n"
            "`/allow <chat_id_или_юзернейм>` (например: `/allow -100123456789` или `/allow @mygroup`)"
        )
    await _safe_send_message(update, text, parse_mode="Markdown")


async def cmd_allow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a chat to the whitelist (Owner only)."""
    user = update.effective_user
    if not user or user.id != TELEGRAM_OWNER_ID:
        return

    if not context.args:
        await _safe_send_message(
            update,
            "Использование: `/allow <chat_id_или_юзернейм>`\nПример: `/allow -100123456789` или `/allow @mygroup`",
            parse_mode="Markdown",
        )
        return

    identifier = context.args[0]
    res = whitelist_mgr.add_chat(identifier)
    await _safe_send_message(update, res.get("message", "Готово."))


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a chat from the whitelist (Owner only)."""
    user = update.effective_user
    if not user or user.id != TELEGRAM_OWNER_ID:
        return

    if not context.args:
        await _safe_send_message(
            update,
            "Использование: `/remove <chat_id_или_юзернейм>`\nПример: `/remove -100123456789`",
            parse_mode="Markdown",
        )
        return

    identifier = context.args[0]
    res = whitelist_mgr.remove_chat(identifier)
    await _safe_send_message(update, res.get("message", "Готово."))


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show IDs of current user and chat."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    text = (
        f"ℹ️ **Информация об идентификаторах:**\n\n"
        f"• **Ваш User ID**: `{user.id}` ({user.first_name})\n"
        f"• **Chat ID**: `{chat.id}`\n"
        f"• **Chat Type**: `{chat.type}`\n"
        f"• **Chat Title/Username**: `{chat.title or chat.username or 'Личный диалог'}`\n\n"
        f"*(Чтобы разрешить этот чат, владелец может отправить: `/allow {chat.id}`)*"
    )
    await _safe_send_message(update, text, parse_mode="Markdown")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    session_id = chat.id if chat.type in ("group", "supergroup", "channel") else user.id
    reset_chat(session_id)
    await _safe_send_message(update, "🔄 История диалога очищена. Начинаем с чистого листа!")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    user = update.effective_user
    if not user or user.id != TELEGRAM_OWNER_ID:
        return

    await _safe_send_message(
        update,
        "📖 **Примеры запросов и команд:**\n\n"
        "🛠️ **Создание и отправка таблиц в чат:**\n"
        "• *«Создай таблицу Склад с колонками: ID, Товар, Количество, Цена, Статус»*\n"
        "• *«Создай таблицу Заказы и отправь ссылку и отчет в чат @mygroup»*\n\n"
        "🎨 **Дизайн и стили:**\n"
        "• *«Оформи таблицу в красивом современном синем стиле»*\n"
        "• *«Сделай черную рамку вокруг таблицы и серую сетку внутри»*\n\n"
        "📊 **Учет данных и строки:**\n"
        "• *«Запиши заказ: Иван, Ноутбук, 75000, Оплачен»*\n"
        "• *«Посчитай сумму в колонке Сумма»*\n"
        "• *«Очисти строки кроме шапки»*\n\n"
        "🛡️ **Управление разрешенными чатами:**\n"
        "• `/allow <chat_id>` — разрешить группе работать с ботом\n"
        "• `/remove <chat_id>` — отозвать разрешение у группы\n"
        "• `/whitelist` — список разрешенных чатов\n"
        "• `/id` — узнать Chat ID группы",
        parse_mode="Markdown",
    )


# ── Text & Photo message handlers with strict security ─────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages according to security and group rules."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    is_owner = (user.id == TELEGRAM_OWNER_ID)

    # 1. Private chat handling
    if chat.type == "private":
        if not is_owner:
            logger.info("Blocked private message from unauthorized user %s (id=%s)", user.first_name, user.id)
            await _safe_send_message(
                update,
                f"Здравствуйте! Я персональный ИИ-ассистент, созданный моим владельцем ({OWNER_NAME}).\n\n"
                f"Я подчиняюсь исключительно его командам и действую только от его имени и по его разрешению. "
                f"Посторонние запросы в личных сообщениях заблокированы.\n\n"
                f"Если вам нужно внести данные в Google Таблицу или получить доступ, пожалуйста, обратитесь напрямую к {OWNER_NAME}.",
            )
            return

        # Owner in private chat — full access
        logger.info("Owner %s: %s", user.first_name, text[:80])
        await _safe_typing(update)
        try:
            response = await get_agent_response_async(user.id, text)
            for i in range(0, len(response), _TG_MAX_LEN):
                chunk = response[i : i + _TG_MAX_LEN]
                await _safe_send_message(update, chunk)
        except Exception:
            logger.exception("Error processing owner text")
            await _safe_send_message(update, "❌ Ошибка при обработке сообщения. Попробуйте команду /reset.")
        return

    # 2. Group / Supergroup / Channel handling
    if chat.type in ("group", "supergroup", "channel"):
        # Check whitelist
        if not whitelist_mgr.is_chat_allowed(chat.id, chat.username):
            # SILENT IGNORE for non-whitelisted chats
            return

        # Determine if message is addressed to the bot or mentions Google Sheets
        bot_username = (context.bot.username or "agenttgh_bot").lower()
        text_lower = text.lower()

        is_bot_mentioned = (f"@{bot_username}" in text_lower) or (
            update.message.reply_to_message
            and update.message.reply_to_message.from_user
            and update.message.reply_to_message.from_user.id == context.bot.id
        )

        sheets_keywords = [
            "таблиц", "sheet", "гугл", "google", "запиши", "записать",
            "внести", "внеси", "добавь", "строк", "ячейк", "колонк", "столбец",
            "статус", "заказ", "клиент", "сумм", "оплат", "расход", "доход",
            "цен", "отчет", "покажи", "данные", "создай", "удали", "измени", "обнови"
        ]
        has_sheets_intent = any(k in text_lower for k in sheets_keywords)

        # In group, if message is not addressed to bot and doesn't mention sheets/data, stay silent
        if not is_bot_mentioned and not has_sheets_intent:
            return

        logger.info("Group '%s' (id=%s) message from %s (owner=%s): %s", chat.title, chat.id, user.first_name, is_owner, text[:80])
        await _safe_typing(update)

        if is_owner:
            prompt = f"[Сообщение от Владельца ({OWNER_NAME}) в группе '{chat.title}']: {text}"
        else:
            prompt = (
                f"[Запрос в разрешенном чате '{chat.title}' от участника {user.first_name} (ID: {user.id})]: {text}\n\n"
                f"Инструкция: ты персональный ассистент, действующий исключительно от имени {OWNER_NAME}. "
                f"Проанализируй запрос участника: действительно ли он касается Google Таблицы. "
                f"Если да — определи точные ячейки/строки/колонки и внеси необходимые изменения через соответствующие инструменты. "
                f"Ответь четко и вежливо от имени {OWNER_NAME}: '✅ От имени {OWNER_NAME}: [описание внесенных изменений]'. "
                f"Если запрос НЕ касается Google Таблицы — вежливо поясни, что в этом чате ты помогаешь с учетом данных в Google Таблицах от имени {OWNER_NAME}."
            )

        try:
            response = await get_agent_response_async(chat.id, prompt)
            for i in range(0, len(response), _TG_MAX_LEN):
                chunk = response[i : i + _TG_MAX_LEN]
                await _safe_send_message(update, chunk)
        except Exception:
            logger.exception("Error processing group message")
            await _safe_send_message(update, "❌ Ошибка при обработке запроса в таблице.")
        return


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo messages according to permissions."""
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or not update.message or not update.message.photo:
        return

    is_owner = (user.id == TELEGRAM_OWNER_ID)
    caption = update.message.caption or ""

    # 1. Private chat
    if chat.type == "private":
        if not is_owner:
            await _safe_send_message(
                update,
                f"Здравствуйте! Я персональный ИИ-ассистент, созданный моим владельцем ({OWNER_NAME}).\n"
                f"Я подчиняюсь исключительно его командам. Посторонние фото и запросы в личных сообщениях заблокированы.",
            )
            return

        session_id = user.id
        prompt = caption or "Проанализируй это фото и внеси данные в Google Таблицу при необходимости."

    # 2. Group chat
    elif chat.type in ("group", "supergroup", "channel"):
        if not whitelist_mgr.is_chat_allowed(chat.id, chat.username):
            return

        session_id = chat.id
        prompt = (
            f"[Фото от {user.first_name} в группе '{chat.title}']: {caption or 'Распознай данные с фото и внеси в Google Таблицу'}\n"
            f"(Действуй от имени {OWNER_NAME}. Проанализируй фото, если это чек/документ/таблица — запиши в Google Таблицу и подтверди от имени {OWNER_NAME})."
        )
    else:
        return

    await _safe_typing(update)

    try:
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()

        buf = io.BytesIO()
        await tg_file.download_to_memory(buf)
        image_bytes = buf.getvalue()

        response = await get_agent_response_async(
            session_id, prompt, image_bytes=image_bytes, mime_type="image/jpeg"
        )

        for i in range(0, len(response), _TG_MAX_LEN):
            chunk = response[i : i + _TG_MAX_LEN]
            await _safe_send_message(update, chunk)

    except Exception:
        logger.exception("Error processing photo from user %s", user.id)
        await _safe_send_message(
            update, "❌ Не удалось обработать фото. Попробуйте ещё раз или сделать /reset."
        )


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by Updates."""
    logger.warning("Update '%s' caused error: %s", update, context.error)


# ── Health check HTTP server for Cloud Hosting (Render, Railway, Fly.io) ──
class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK: Telegram Gemini AI Bot is running 24/7!\n")

    def log_message(self, format: str, *args: object) -> None:
        pass


def _start_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    try:
        server = HTTPServer(("0.0.0.0", port), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("🌐 Healthcheck HTTP server started on port %d (ready for Render/Railway)", port)
    except Exception as e:
        logger.debug("Health server could not start on port %d: %s", port, e)


# ── Main ──────────────────────────────────────────────────

def main() -> None:
    """Start the bot with robust network timeouts and strict permissions."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не задан в .env!")
        return

    _start_health_server()

    # Generous HTTP timeouts to survive DNS and network latency
    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=35.0,
        write_timeout=20.0,
        pool_timeout=15.0,
    )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("whitelist", cmd_whitelist))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("id", cmd_id))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(global_error_handler)

    logger.info("🤖 Бот запущен! Владелец: %s (ID: %s)", OWNER_NAME, TELEGRAM_OWNER_ID)
    logger.info("🛡️ Разрешенные чаты: %s", whitelist_mgr.get_all() or "[список пуст]")

    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=False,
                bootstrap_retries=-1,
            )
            break
        except Exception as e:
            logger.warning("Сбой сети: %s. Переподключение через 5 секунд...", e)
            import time
            time.sleep(5)


if __name__ == "__main__":
    main()
