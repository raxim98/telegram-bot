"""Gemini AI agent with Google Sheets function-calling and multimodal Vision.

Supports:
  • Chat with conversation history (Simple Memory)
  • Multimodal analysis (photos, receipts, documents, tables)
  • Google Sheets tools (batch add, read, inspect, clone/create, format, formula)
  • Telegram chat assistant helper
  • Strict Owner Authorization & Group Chat rules
"""

from __future__ import annotations

import asyncio
import logging
import re

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, OWNER_NAME, TELEGRAM_OWNER_ID
from sheets_tools import (
    add_row,
    add_rows,
    clear_sheet_rows,
    copy_data_from_spreadsheet,
    create_spreadsheet,
    create_table_sheet,
    delete_spreadsheet,
    delete_table_sheet,
    execute_custom_sheets_request,
    format_cells,
    freeze_panes,
    get_rows,
    get_sheet_info,
    inspect_spreadsheet,
    list_accessible_spreadsheets,
    manage_chat_whitelist,
    manage_worksheets,
    merge_or_unmerge_cells,
    open_spreadsheet_by_name,
    rename_spreadsheet,
    resize_dimensions,
    send_telegram_message,
    set_active_spreadsheet,
    set_cell_borders,
    share_sheet_summary_to_telegram,
    sort_or_filter_range,
    style_table_preset,
    update_cells_or_formulas,
)

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────
SYSTEM_PROMPT = f"""\
Ты — интеллектуальный персональный AI-ассистент, созданный твоим владельцем ({OWNER_NAME}).
Ты действуешь исключительно от его имени, подчиняешься его указаниям и управляешь Google Таблицами.

Твои возможности и инструменты:
1. СОЗДАНИЕ, УДАЛЕНИЕ И ПОИСК ТАБЛИЦ:
   - `create_table_sheet`: СОЗДАТЬ НОВУЮ ТАБЛИЦУ (вкладку/лист с нужными колонками и красивым оформлением). Используй ВСЕГДА, когда просят: «Создай таблицу [Название] с колонками: A, B, C»!
   - `create_spreadsheet`: создать НОВЫЙ отдельный документ Google Таблицы на Google Диске.
   - `rename_spreadsheet`: ПЕРЕИМЕНОВАТЬ Google Таблицу (сам документ).
   - `delete_spreadsheet`: УДАЛИТЬ Google Таблицу с Google Диска (разрешено ТОЛЬКО по прямой команде владельца {OWNER_NAME}).
   - `delete_table_sheet`: УДАЛИТЬ конкретную таблицу/вкладку по имени (например, «Удали таблицу Склад»).
   - `open_spreadsheet_by_name`: ОТКРЫТЬ ТАБЛИЦУ ПО НАЗВАНИЮ (например «2026», «Отчет 2025»). Находит таблицу и делает её активной!
   - `list_accessible_spreadsheets`: СПИСОК ДОСТУПНЫХ ТАБЛИЦ. Вызови, когда спрашивают, какие таблицы видны или к каким есть доступ.
   - `set_active_spreadsheet`: переключить активную таблицу по ссылке или ID.

2. ДАННЫЕ В ТАБЛИЦАХ:
   - `add_row`: добавить одну строку.
   - `add_rows`: ПАКЕТНОЕ добавление сразу нескольких строк (передавай JSON-массив массивов). Используй ВСЕГДА для 2+ строк!
   - `clear_sheet_rows`: ОЧИСТИТЬ строки в таблице (`keep_headers=True` сохраняет шапку, `keep_headers=False` стирает всё).
   - `get_rows`: прочитать строки из таблицы.
   - `get_sheet_info`: узнать список листов и структуру таблицы.
   - `inspect_spreadsheet`: изучить ЛЮБУЮ таблицу Google по ссылке или ID.
   - `copy_data_from_spreadsheet`: скопировать строки из другой таблицы.

3. ФОРМУЛЫ И РАСЧЕТЫ:
   - `update_cells_or_formulas`: записать в ячейку или диапазон формулу Google Sheets (`=SUM(...)`, `=AVERAGE(...)`, `=VLOOKUP(...)`, `=COUNTIF(...)`) или точечные значения.

4. ОФОРМЛЕНИЕ, ЦВЕТА И ШРИФТЫ:
   - `format_cells`: изменить заливку ячеек (`bg_color`), цвет текста (`text_color`), начертание (`bold`, `italic`, `underline`, `strikethrough`), размер шрифта (`font_size`), выравнивание (`horizontal_align`), перенос слов (`wrap_strategy`='WRAP').
   - `set_cell_borders`: установить рамки/границы (`border_type`='ALL'/'OUTER'/'INNER'/'CLEAR', `border_style`='SOLID'/'SOLID_MEDIUM'/'SOLID_THICK'/'DASHED'/'DOTTED'/'DOUBLE', цвет `border_color`).
   - `style_table_preset`: применить ГОТОВЫЙ ДИЗАЙНЕРСКИЙ СТИЛЬ к таблице ('MODERN_BLUE', 'EMERALD', 'DARK_ELEGANT', 'WARM_CORAL', 'MINIMAL_GRAY').

5. ГЕОМЕТРИЯ И УПРАВЛЕНИЕ ВКЛАДКАМИ:
   - `merge_or_unmerge_cells`: объединить ячейки ('MERGE_ALL', 'MERGE_ROWS', 'MERGE_COLUMNS') или разъединить ('UNMERGE').
   - `freeze_panes`: закрепить строку заголовка (`rows=1`) и/или столбец (`cols=1`).
   - `resize_dimensions`: изменить ширину столбцов или высоту строк (автоподбор по тексту `pixel_size=0`).
   - `manage_worksheets`: создать новый лист ('add'), удалить ('delete'), переименовать ('rename'), дублировать ('duplicate') или цвет ярлычка.
   - `sort_or_filter_range`: сортировка диапазона или автофильтр.
   - `execute_custom_sheets_request`: произвольные запросы batchUpdate.

6. ВЗАИМОДЕЙСТВИЕ С ЧАТАМИ TELEGRAM И БЕЛЫМ СПИСКОМ:
   - `send_telegram_message`: отправить текстовое сообщение в указанный Telegram-чат/группу (`chat_id_or_username`).
   - `share_sheet_summary_to_telegram`: сформировать превью-таблицу с данными и прямой ссылкой и отправить её в Telegram-чат.
   - `manage_chat_whitelist`: добавить чат в белый список ('add'), удалить ('remove') или показать список ('list').

7. ЗРЕНИЕ (VISION):
   - Фото чеков, квитанций, расписаний, таблиц и документов — извлеки данные и запиши в таблицу.

8. ⚡ КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА:
   A) СОЗДАНИЕ ТАБЛИЦ С НУЛЯ:
      Когда ты создаешь новую таблицу с нуля (через `create_table_sheet` или `create_spreadsheet`):
      - В ответе Telegram ОБЯЗАТЕЛЬНО отправь прямую кликабельную ссылку на таблицу: [Нажмите сюда, чтобы открыть таблицу](URL).
      - Нарисуй красивое Markdown-превью структуры таблицы с колонками:
        | Колонка 1 | Колонка 2 | Колонка 3 |
        | --- | --- | --- |
      - Если пользователь попросил отправить созданную таблицу в другой чат или группу — вызови `send_telegram_message` или `share_sheet_summary_to_telegram`!

   B) РАБОТА В ГРУППОВЫХ ЧАТАХ:
      - Ты действуешь от имени {OWNER_NAME}.
      - В группах участники могут просить внести данные в Google Sheets (например: «запиши заказ», «измени цену», «добавь клиента», «обнови статус»).
      - Всегда внимательно анализируй: действительно ли запрос касается Google Таблицы.
      - Определи точные ячейки, колонки и строки для изменения. Выполни нужное действие.
      - Ответь вежливо и четко от имени {OWNER_NAME}: «✅ От имени {OWNER_NAME}: данные внесены в Google Таблицу [краткое описание]».
      - Участникам групп СТРОГО ЗАПРЕЩЕНО удалять всю таблицу целиком (`delete_spreadsheet`). При таких попытках вежливо откажи.
      - Если сообщение в группе НЕ касается Google Таблицы — вежливо напомни, что в этом чате ты помогаешь с учетом данных в Google Таблицах от имени {OWNER_NAME}.
"""

# ── Gemini client singleton ───────────────────────────────
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ── Per-session chat sessions (Memory) ─────────────────────
# Sessions can be keyed by user_id (for private) or chat_id (for groups)
_chat_sessions: dict[int, object] = {}

ALL_TOOLS = [
    open_spreadsheet_by_name,
    list_accessible_spreadsheets,
    create_table_sheet,
    delete_table_sheet,
    rename_spreadsheet,
    delete_spreadsheet,
    set_active_spreadsheet,
    add_row,
    add_rows,
    clear_sheet_rows,
    copy_data_from_spreadsheet,
    get_rows,
    get_sheet_info,
    inspect_spreadsheet,
    create_spreadsheet,
    format_cells,
    set_cell_borders,
    merge_or_unmerge_cells,
    freeze_panes,
    resize_dimensions,
    manage_worksheets,
    sort_or_filter_range,
    update_cells_or_formulas,
    style_table_preset,
    execute_custom_sheets_request,
    send_telegram_message,
    share_sheet_summary_to_telegram,
    manage_chat_whitelist,
]


def get_agent_response(
    session_id: int,
    message: str,
    image_bytes: bytes | None = None,
    mime_type: str = "image/jpeg",
) -> str:
    """Send message (and optional photo) to Gemini and return text reply."""
    client = _get_client()

    if session_id not in _chat_sessions:
        logger.info("Creating new chat session for session_id %s", session_id)
        _chat_sessions[session_id] = client.chats.create(
            model="gemini-3.5-flash-lite",
            config=types.GenerateContentConfig(
                tools=ALL_TOOLS,
                system_instruction=SYSTEM_PROMPT,
                temperature=0.7,
            ),
        )

    chat = _chat_sessions[session_id]

    payload: list = []
    if image_bytes:
        payload.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
    payload.append(message or "Что изображено на этом фото? Проанализируй подробно.")

    try:
        response = chat.send_message(payload if len(payload) > 1 else payload[0])
        return response.text or "✅ Задача выполнена."
    except Exception as e:
        logger.exception("Error in agent response for session %s", session_id)
        return f"⚠️ Произошла ошибка: {e}"


async def get_agent_response_async(
    session_id: int,
    message: str,
    image_bytes: bytes | None = None,
    mime_type: str = "image/jpeg",
) -> str:
    """Async wrapper for telegram bot."""
    return await asyncio.to_thread(
        get_agent_response, session_id, message, image_bytes, mime_type
    )


def reset_chat(session_id: int) -> None:
    """Clear conversation history for a user or group."""
    _chat_sessions.pop(session_id, None)


def generate_chat_reply(chat_title: str, recent_messages: list[dict], user_name: str) -> str:
    """Formulate an authentic reply for a Telegram chat from the user's perspective.

    Used by the Userbot.
    """
    client = _get_client()
    messages_formatted = "\n".join(
        f"{m.get('sender', 'Собеседник')}: {m.get('text', '')}"
        for m in recent_messages
    )

    prompt = f"""\
Ты действуешь от имени пользователя по имени {user_name} в Telegram-чате "{chat_title}".
Твоя задача — написать короткий, естественный и уместный ответ на последнее сообщение в переписке.

Контекст переписки:
{messages_formatted}

Правила:
1. Пиши кратко, в обычном разговорном стиле Telegram (как живой человек, без шаблонных фраз).
2. Не представляйся искусственным интеллектом, пиши от первого лица ({user_name}).
3. Напиши ТОЛЬКО текст самого сообщения для отправки.
"""
    try:
        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )
        return resp.text.strip() if resp.text else ""
    except Exception as e:
        logger.error("Failed to generate chat reply: %s", e)
        return ""


# ── Intent Detection & Confirmed Execution for Userbot ───────

def detect_sheets_intent(text: str) -> dict | None:
    """Analyze if incoming message requests a Google Sheets modification.

    Returns dict with action_summary or None if not related.
    """
    if not text:
        return None

    lower = text.lower()
    keywords = [
        "таблиц", "sheet", "гугл", "google", "запиши", "записать",
        "добавь", "внести", "внеси", "поменяй", "измени", "обнови",
        "строк", "ячейк", "колонк", "столбец", "статус", "заказ",
        "клиент", "сумм", "оплат", "расход", "доход", "цен", "очисти"
    ]
    if not any(k in lower for k in keywords):
        return None

    client = _get_client()
    prompt = f"""\
Проанализируй текст сообщения от участника чата:
"{text}"

Вопрос: Содержит ли это сообщение просьбу или команду внести, добавить, изменить, очистить или обновить данные в Google Таблицах?
- Если ДА: напиши краткое понятное резюме действия (1 строка на русском, например: "Добавить заказ: 50 коробок чая по 10000 сум", "Изменить статус клиента Иван на Оплачено").
- Если НЕТ (это просто вопрос, приветствие или обычный разговор): ответь строго одним словом: НЕТ
"""
    try:
        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )
        ans = resp.text.strip() if resp.text else ""
        if not ans or ans.upper() == "НЕТ" or "НЕТ" in ans.upper()[:4]:
            return None
        # Clean up leading prefixes like "ДА: " or "Да, "
        cleaned_ans = re.sub(r"^(да|yes)[:,\s-]*", "", ans, flags=re.IGNORECASE).strip()
        return {
            "is_sheets_request": True,
            "action_summary": cleaned_ans or ans,
            "original_text": text,
        }
    except Exception as e:
        logger.error("Error detecting sheets intent: %s", e)
        return None


def execute_confirmed_sheets_request(action_prompt: str) -> str:
    """Execute confirmed Google Sheets modification through Gemini agent and Sheets tools."""
    client = _get_client()
    exec_chat = client.chats.create(
        model="gemini-3.5-flash-lite",
        config=types.GenerateContentConfig(
            tools=ALL_TOOLS,
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
        ),
    )
    prompt = f"[Подтвержденное действие от Владельца ({OWNER_NAME})]: {action_prompt}"
    try:
        resp = exec_chat.send_message(prompt)
        return resp.text or "✅ Данные успешно внесены в Google Таблицу."
    except Exception as e:
        logger.exception("Failed to execute confirmed sheets request: %s", e)
        return f"⚠️ Ошибка выполнения: {e}"
