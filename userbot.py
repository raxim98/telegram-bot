"""Telegram Userbot — operates from YOUR personal Telegram account.

Key Features:
  • Acts on behalf of the creator (Рахим) across all Telegram chats.
  • Blacklist / Exclude system: ignores all chats in excluded_chats.json.
  • Two-Factor Confirmation: ANY Google Sheets modification requested by another user
    MUST be approved by the creator via '.confirm REQ-ID' in Saved Messages or chat.
  • All Google Sheets modifications are executed via the Telegram Bot tools engine.
  • Human-like typing action and natural conversational AI responses.
  • Creator controls: .exclude, .include, .list_excluded, .confirm, .reject, .status, .help.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, User

from chat_filter import chat_filter_mgr
from config import OWNER_NAME, TELEGRAM_API_HASH, TELEGRAM_API_ID, TELEGRAM_USER_SESSION
from gemini_agent import (
    detect_sheets_intent,
    execute_confirmed_sheets_request,
    generate_chat_reply,
)

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
logger = logging.getLogger("userbot")


async def run_userbot():
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        print("❌ TELEGRAM_API_ID или TELEGRAM_API_HASH не заданы в .env!")
        print("Получите их бесплатно на https://my.telegram.org в разделе 'API development tools'.")
        return

    logger.info("🚀 Запуск AI-юзербота от имени %s...", OWNER_NAME)
    if TELEGRAM_USER_SESSION:
        session = StringSession(TELEGRAM_USER_SESSION)
        logger.info("🔑 Используется строковая сессия Telethon (из переменной окружения)")
    else:
        session = "user_session"
        logger.info("📁 Используется локальный файл сессии user_session.session")

    client = TelegramClient(session, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await client.start()

    me = await client.get_me()
    logger.info("✅ Юзербот успешно авторизован! Аккаунт: %s (@%s, ID: %s)", me.first_name, me.username, me.id)
    logger.info("🛡️ Исключенные чаты (где бот НЕ отвечает): %s", chat_filter_mgr.get_excluded() or "[нет исключений, отвечает везде]")

    # ── Command handler for Creator (Self / Outgoing messages) ────
    @client.on(events.NewMessage(outgoing=True))
    async def on_creator_command(event):
        text_raw = (event.text or "").strip()
        text_lower = text_raw.lower()
        if not text_lower:
            return

        chat = await event.get_chat()
        chat_title = getattr(chat, "title", None) or getattr(chat, "first_name", "Этот чат")
        is_saved_messages = (event.chat_id == me.id)

        # ── 1. САМЫЙ ПРОСТОЙ СПОСОБ: ОТКЛЮЧИТЬ ЧАТ (СТОП) ─────────────
        stop_keywords = [
            ".exclude", ".стоп", ".stop", ".выкл",
            "не отвечай тут", "не отвечай здесь", "не отвечай в этом чате",
            "стоп бот", "отключись тут", "отключись здесь", "хватит отвечать", "молчи тут"
        ]
        if any(text_lower == p or text_lower.startswith(p + " ") for p in stop_keywords):
            arg = ""
            for p in stop_keywords:
                if text_lower.startswith(p):
                    arg = text_raw[len(p):].strip()
                    break

            target = arg or str(event.chat_id)
            res = chat_filter_mgr.exclude_chat(target)
            msg = f"🚫 **Автоответы отключены в чате:** '{chat_title}'"

            if not is_saved_messages:
                # Quiet confirmation in Saved Messages so colleagues aren't spammed
                try:
                    await client.send_message("me", msg)
                except Exception:
                    pass
                await event.reply("🚫 [Автоответы отключены]")
            else:
                await event.reply(res.get("message", msg))
            return

        # ── 2. САМЫЙ ПРОСТОЙ СПОСОБ: ВКЛЮЧИТЬ ЧАТ (СТАРТ) ────────────
        start_keywords = [
            ".include", ".старт", ".start", ".вкл",
            "отвечай тут", "отвечай здесь", "отвечай в этом чате",
            "старт бот", "включись тут", "включись здесь"
        ]
        if any(text_lower == p or text_lower.startswith(p + " ") for p in start_keywords):
            arg = ""
            for p in start_keywords:
                if text_lower.startswith(p):
                    arg = text_raw[len(p):].strip()
                    break

            target = arg or str(event.chat_id)
            res = chat_filter_mgr.include_chat(target)
            msg = f"✅ **Автоответы включены в чате:** '{chat_title}'"

            if not is_saved_messages:
                try:
                    await client.send_message("me", msg)
                except Exception:
                    pass
                await event.reply("✅ [Автоответы включены]")
            else:
                await event.reply(res.get("message", msg))
            return

        # ── 3. УПРАВЛЕНИЕ ИЗ «ИЗБРАННОГО» ПРОСТЫМИ СЛОВАМИ ───────────
        if is_saved_messages:
            if text_lower.startswith("не отвечай в ") or text_lower.startswith("отключи чат ") or text_lower.startswith("заблокируй чат "):
                target = text_raw.split(" ", 3)[-1].strip()
                res = chat_filter_mgr.exclude_chat(target)
                await event.reply(f"🚫 Готово! Чат '{target}' добавлен в список исключений.")
                return

            if text_lower.startswith("отвечай в ") or text_lower.startswith("включи чат ") or text_lower.startswith("разблокируй чат "):
                target = text_raw.split(" ", 2)[-1].strip()
                res = chat_filter_mgr.include_chat(target)
                await event.reply(f"✅ Готово! Чат '{target}' возвращен в разрешенные.")
                return

        # ── 4. СПИСОК ЧАТОВ И РЕЖИМ ──────────────────────────────────
        list_triggers = [
            ".list_excluded", ".список", "список чатов", "какие чаты отключены",
            "где не отвечаешь", "исключения", "белый список", "разрешенные чаты",
            "где отвечаешь", "список разрешенных", ".whitelist"
        ]
        if text_lower in list_triggers:
            if chat_filter_mgr.whitelist_mode:
                allowed = chat_filter_mgr.get_allowed()
                # Friendly display of unique items
                friendly_allowed = [
                    "Sevara", "Onam", "Сайдамир", "хasanovich.11", "Komol",
                    "Доклады Боймуратов Р,Р", "Ойбек ака", "СК Группа", "ходиев мирориф"
                ]
                extra = [a for a in allowed if not any(f.lower() in a for f in friendly_allowed)]
                display_list = friendly_allowed + extra
                items_str = "\n".join(f"• ✅ **{c}**" for c in display_list)
                msg = (
                    "🔒 **Режим работы: ТОЛЬКО РАЗРЕШЕННЫЕ ЧАТЫ (Белый список)**\n\n"
                    f"Юзербот отвечает **исключительно** в следующих диалогах ({len(display_list)}):\n\n"
                    f"{items_str}\n\n"
                    "🚫 **Все остальные чаты полностью исключены!**\n"
                    "💡 *Чтобы добавить чат, напишите в нем 'Отвечай тут' или в Избранное 'Отвечай в <название>'.*"
                )
            else:
                excluded = chat_filter_mgr.get_excluded()
                if excluded:
                    msg = "🚫 **Список исключенных чатов (где юзербот НЕ отвечает):**\n\n" + "\n".join(f"• `{c}`" for c in excluded)
                else:
                    msg = "✅ Юзербот отвечает во всех чатах (список исключений пуст)."
            await event.reply(msg)
            return

        if text_lower in ("отвечай во всех чатах", "разреши все чаты", "выключи белый список"):
            chat_filter_mgr.set_whitelist_mode(False)
            await event.reply("🔓 **Режим изменен:** теперь юзербот отвечает во всех чатах (кроме черного списка).")
            return

        if text_lower in ("отвечай только в разрешенных", "включи белый список", "только белый список"):
            chat_filter_mgr.set_whitelist_mode(True)
            await event.reply("🔒 **Режим изменен:** теперь юзербот отвечает **ТОЛЬКО** в разрешенных чатах!")
            return

        # ── 5. ПОДТВЕРЖДЕНИЕ ЗАЯВКИ (.confirm / да / подтверждаю) ─────
        confirm_words = [".confirm", "да ", "подтверждаю "]
        is_confirm = any(text_lower.startswith(w) for w in confirm_words)
        if is_confirm:
            req_id = text_raw.split(maxsplit=1)[-1].upper().strip()
            req = chat_filter_mgr.pop_pending_request(req_id)
            if not req:
                await event.reply(f"❌ Заявка `{req_id}` не найдена или уже была обработана.")
                return

            await event.reply(f"⏳ Одобрено! Выполняю изменения в Google Таблице по заявке `{req_id}`...")
            result = execute_confirmed_sheets_request(req["action_summary"] or req["original_text"])

            # Send confirmation report to creator
            await client.send_message("me", f"✅ **Заявка {req_id} выполнена!**\n\n{result}")

            # Send confirmation message into the original chat
            try:
                confirm_chat_text = f"✅ Рахим подтвердил изменения. Данные внесены в Google Таблицу:\n*{req['action_summary']}*"
                await client.send_message(
                    req["chat_id"],
                    confirm_chat_text,
                    reply_to=req.get("reply_to_msg_id"),
                )
            except Exception as ce:
                logger.warning("Could not send confirmation to chat %s: %s", req["chat_id"], ce)
            return

        # ── 6. ОТКЛОНЕНИЕ ЗАЯВКИ (.reject / нет / отклонить) ─────────
        reject_words = [".reject", "нет ", "отклонить "]
        is_reject = any(text_lower.startswith(w) for w in reject_words)
        if is_reject:
            req_id = text_raw.split(maxsplit=1)[-1].upper().strip()
            req = chat_filter_mgr.pop_pending_request(req_id)
            if not req:
                await event.reply(f"❌ Заявка `{req_id}` не найдена или уже была обработана.")
                return
            await event.reply(f"🚫 Заявка `{req_id}` отклонена.")
            return

        # ── 7. СТАТУС ────────────────────────────────────────────────
        if text_lower in (".status", ".статус", "статус"):
            pending = chat_filter_mgr.list_pending()
            excluded = chat_filter_mgr.get_excluded()
            text_status = (
                f"📊 **Статус AI-юзербота:**\n\n"
                f"• Владелец: {me.first_name} (@{me.username or 'без username'})\n"
                f"• Исключенных чатов: {len(excluded)}\n"
                f"• Заявок в ожидании: {len(pending)}\n"
            )
            if pending:
                text_status += "\n**Ожидают подтверждения:**\n"
                for p in pending:
                    text_status += f"• `{p['req_id']}`: {p['sender_name']} в чате '{p['chat_title']}' -> *{p['action_summary']}*\n"
            await event.reply(text_status)
            return

        # ── 8. ПОМОЩЬ / СПРАВКА ──────────────────────────────────────
        if text_lower in (".help", ".помощь", ".команды", "помощь"):
            await event.reply(
                "💡 **Самый простой способ управлять чатами:**\n\n"
                "• Напишите в любом чате: **Не отвечай тут** (или `.стоп`)\n"
                "• Чтобы вернуть: **Отвечай тут** (или `.старт`)\n\n"
                "• В «Избранном» можно написать:\n"
                "  *Не отвечай в Korzinka CK*\n"
                "  *Отвечай в Korzinka CK*\n"
                "  *Список чатов*\n"
                "  *Статус*"
            )
            return

    # ── Incoming messages handler ─────────────────────────────────
    @client.on(events.NewMessage(incoming=True))
    async def on_incoming_message(event):
        if event.out:
            return

        chat = await event.get_chat()
        chat_username = getattr(chat, "username", None)
        chat_title = getattr(chat, "title", None) or getattr(chat, "first_name", "Личный диалог")

        # 1. Check Blacklist / Excluded chats
        if not chat_filter_mgr.is_allowed(event.chat_id, chat_username, chat_title):
            logger.info("Chat '%s' (id=%s) is in excluded list. Ignoring.", chat_title, event.chat_id)
            return

        # 2. Ignore broadcast channels or bots
        sender = await event.get_sender()
        if isinstance(sender, Channel) and not getattr(chat, "megagroup", False):
            return
        if isinstance(sender, User) and getattr(sender, "bot", False):
            return

        sender_name = getattr(sender, "first_name", "Собеседник")
        message_text = (event.text or "").strip()
        if not message_text:
            return

        logger.info("Входящее сообщение в разрешенном чате '%s' от %s: %s", chat_title, sender_name, message_text[:80])

        # 3. Check if message is a Google Sheets modification request
        intent = detect_sheets_intent(message_text)
        if intent and intent.get("is_sheets_request"):
            action_summary = intent["action_summary"]
            logger.info("Обнаружен запрос к Google Sheets: %s. Требуется подтверждение владельца!", action_summary)

            # Create pending request
            req_id = chat_filter_mgr.create_pending_request(
                chat_id=event.chat_id,
                chat_title=chat_title,
                sender_name=sender_name,
                sender_id=event.sender_id,
                original_text=message_text,
                action_summary=action_summary,
                reply_to_msg_id=event.id,
            )

            # Notify creator in Saved Messages ("me")
            notice_text = (
                f"🔔 **Новый запрос на изменение Google Таблицы!**\n\n"
                f"• **Чат**: {chat_title}\n"
                f"• **От кого**: {sender_name} (ID: `{event.sender_id}`)\n"
                f"• **Текст**: «{message_text}»\n"
                f"• **Предлагаемое действие**: `{action_summary}`\n\n"
                f"👉 **Одобрить**: `.confirm {req_id}`\n"
                f"👉 **Отклонить**: `.reject {req_id}`"
            )
            try:
                await client.send_message("me", notice_text)
            except Exception as ne:
                logger.error("Could not notify in Saved Messages: %s", ne)

            # Reply to requester in the chat
            reply_notice = "Принял ваш запрос! Согласую его с Рахимом и после подтверждения внесу данные в таблицу."
            async with client.action(event.chat_id, "typing"):
                await asyncio.sleep(1.5)
            await event.reply(reply_notice)
            return

        # 4. Ordinary conversation — formulate authentic reply as Рахим
        history = []
        async for msg in client.iter_messages(event.chat_id, limit=6):
            if msg.text:
                s = await msg.get_sender()
                s_name = getattr(s, "first_name", "Собеседник")
                history.append({"sender": s_name, "text": msg.text})

        history.reverse()

        reply_text = generate_chat_reply(
            chat_title=chat_title,
            recent_messages=history,
            user_name=me.first_name,
        )

        if not reply_text:
            return

        logger.info("Отправляю ответ в чат '%s' от имени %s: %s", chat_title, me.first_name, reply_text)

        # Human-like typing delay
        async with client.action(event.chat_id, "typing"):
            delay = min(max(len(reply_text) * 0.04, 1.5), 4.5)
            await asyncio.sleep(delay)

        await event.reply(reply_text)

    logger.info("📡 Юзербот запущен и слушает все разрешенные чаты...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(run_userbot())
