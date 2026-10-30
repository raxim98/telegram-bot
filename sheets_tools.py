"""Google Sheets tools for the AI agent.

Supports dynamic active spreadsheets, batch row insertion, full or partial clearing,
inspecting arbitrary sheets, cloning, and copying between sheets.
"""

from __future__ import annotations

import json
import re
import gspread
import gspread.utils

import httpx
from whitelist_manager import whitelist_mgr
from config import (
    TELEGRAM_BOT_TOKEN,

    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SHEETS_SPREADSHEET_ID,
    USER_GOOGLE_EMAIL,
)

# ── Client singleton & Active spreadsheet ─────────────────
_client: gspread.Client | None = None
_current_spreadsheet_id: str = GOOGLE_SHEETS_SPREADSHEET_ID


def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        if GOOGLE_SERVICE_ACCOUNT_JSON:
            try:
                info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
                _client = gspread.service_account_from_dict(info)
            except Exception:
                _client = gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)
        else:
            _client = gspread.service_account(filename=GOOGLE_SERVICE_ACCOUNT_FILE)
    return _client


def _extract_sheet_id(url_or_id: str) -> str:
    """Extract 44-character spreadsheet ID from URL or return raw ID."""
    if not url_or_id:
        return ""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()


def _get_spreadsheet(spreadsheet_url_or_id: str = "") -> gspread.Spreadsheet:
    """Return the specified or active spreadsheet."""
    target_id = _extract_sheet_id(spreadsheet_url_or_id) or _current_spreadsheet_id
    gc = _get_client()
    return gc.open_by_key(target_id)


def _get_worksheet(sh: gspread.Spreadsheet, sheet_name: str = "Лист1") -> gspread.Worksheet:
    """Safely find a worksheet by name, case-insensitively, with fallback to first sheet."""
    if not sheet_name:
        return sh.sheet1
    try:
        return sh.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        lower_name = sheet_name.strip().lower()
        for ws in sh.worksheets():
            if ws.title.strip().lower() == lower_name:
                return ws
        if lower_name in ("лист1", "sheet1", "лист 1", "sheet 1"):
            return sh.sheet1
        raise


def _parse_color(val: str | dict | None) -> dict | None:
    """Parse color from HEX (#FF0000), English/Russian names, or return dict."""
    if not val:
        return None
    if isinstance(val, dict):
        return val
    val = str(val).strip().lower()
    named_colors = {
        # Russian
        "синий": "#4285f4",
        "темно-синий": "#1a73e8",
        "тёмно-синий": "#1a73e8",
        "голубой": "#c5dafc",
        "красный": "#ea4335",
        "темно-красный": "#c5221f",
        "тёмно-красный": "#c5221f",
        "зеленый": "#34a853",
        "зелёный": "#34a853",
        "светло-зеленый": "#b7e1cd",
        "светло-зелёный": "#b7e1cd",
        "желтый": "#fbbc05",
        "жёлтый": "#fbbc05",
        "светло-желтый": "#fce8b2",
        "светло-жёлтый": "#fce8b2",
        "оранжевый": "#ff6d01",
        "фиолетовый": "#a142f4",
        "розовый": "#f439a0",
        "серый": "#9aa0a6",
        "светло-серый": "#f1f3f4",
        "темно-серый": "#5f6368",
        "тёмно-серый": "#5f6368",
        "черный": "#000000",
        "чёрный": "#000000",
        "белый": "#ffffff",
        # English
        "blue": "#4285f4",
        "darkblue": "#1a73e8",
        "lightblue": "#c5dafc",
        "red": "#ea4335",
        "darkred": "#c5221f",
        "green": "#34a853",
        "lightgreen": "#b7e1cd",
        "darkgreen": "#137333",
        "yellow": "#fbbc05",
        "lightyellow": "#fce8b2",
        "orange": "#ff6d01",
        "purple": "#a142f4",
        "pink": "#f439a0",
        "cyan": "#24c1e0",
        "teal": "#009688",
        "gray": "#9aa0a6",
        "grey": "#9aa0a6",
        "lightgray": "#f1f3f4",
        "lightgrey": "#f1f3f4",
        "darkgray": "#5f6368",
        "darkgrey": "#5f6368",
        "black": "#000000",
        "white": "#ffffff",
    }
    hex_str = named_colors.get(val, val)
    if hex_str.startswith("#"):
        hex_str = hex_str[1:]
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    if len(hex_str) == 6:
        try:
            r = int(hex_str[0:2], 16) / 255.0
            g = int(hex_str[2:4], 16) / 255.0
            b = int(hex_str[4:6], 16) / 255.0
            return {"red": round(r, 3), "green": round(g, 3), "blue": round(b, 3)}
        except ValueError:
            return None
    return None


def _col_to_index(col: str | int) -> int:
    """Convert column letter ('A', 'B', 'AA') or 1-based number to 1-based integer index."""
    if isinstance(col, int):
        return col
    s = str(col).strip().upper()
    if s.isdigit():
        return int(s)
    idx = 0
    for char in s:
        if 'A' <= char <= 'Z':
            idx = idx * 26 + (ord(char) - ord('A') + 1)
    return max(1, idx)


# ── Tools ─────────────────────────────────────────────────

def set_active_spreadsheet(url_or_id: str) -> dict:
    """Switch the bot's active Google Sheet to a new table by its link or ID.

    Call this whenever the user sends a link to a Google Sheets document, so all
    subsequent commands (add, clear, read) will apply to this new table!

    Args:
        url_or_id: Full URL of the Google Sheet or raw spreadsheet ID.
    """
    global _current_spreadsheet_id
    try:
        new_id = _extract_sheet_id(url_or_id)
        gc = _get_client()
        sh = gc.open_by_key(new_id)
        _current_spreadsheet_id = new_id

        sheets = [ws.title for ws in sh.worksheets()]
        return {
            "status": "success",
            "message": f"Активная таблица переключена на: '{sh.title}' (ID: {new_id})",
            "title": sh.title,
            "sheets": sheets,
            "spreadsheet_id": new_id,
        }
    except gspread.exceptions.SpreadsheetNotFound:
        return {
            "status": "error",
            "message": "Таблица не найдена или к ней не выдан доступ сервисному аккаунту.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def add_row(sheet_name: str = "Лист1", values: str = "", spreadsheet_url_or_id: str = "") -> dict:
    """Add a single new row to a Google Sheets worksheet.

    Args:
        sheet_name: The name of the worksheet tab (e.g. "Лист1").
        values: Comma-separated values for the new row.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)
        row_values = [v.strip() for v in values.split(",")]
        worksheet.append_row(row_values, value_input_option="USER_ENTERED")
        return {
            "status": "success",
            "message": f"Строка добавлена в '{sh.title}' -> '{worksheet.title}'",
            "row": row_values,
        }
    except gspread.exceptions.WorksheetNotFound:
        return {"status": "error", "message": f"Лист '{sheet_name}' не найден в таблице '{sh.title}'."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def add_rows(sheet_name: str = "Лист1", rows_data: str = "", spreadsheet_url_or_id: str = "") -> dict:
    """Add MULTIPLE rows to a worksheet at once (batch insert).

    Use this when adding more than 1 row (e.g. 5, 20, 50 rows) to avoid hitting API limits.

    Args:
        sheet_name: The name of the worksheet tab (e.g. "Лист1").
        rows_data: JSON-encoded list of rows OR newline-separated CSV.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)

        rows: list[list[str]] = []
        try:
            parsed = json.loads(rows_data)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, list):
                        rows.append([str(x).strip() for x in item])
                    elif isinstance(item, str):
                        rows.append([v.strip() for v in item.split(",")])
        except Exception:
            for line in rows_data.strip().splitlines():
                if line.strip():
                    rows.append([v.strip() for v in line.split(",")])

        if not rows:
            return {"status": "error", "message": "Не удалось распознать строки для добавления."}

        worksheet.append_rows(rows, value_input_option="USER_ENTERED")
        return {
            "status": "success",
            "message": f"Успешно добавлено {len(rows)} строк в '{sh.title}' -> '{worksheet.title}'",
            "count": len(rows),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_rows(sheet_name: str = "Лист1", spreadsheet_url_or_id: str = "") -> dict:
    """Read all rows from a Google Sheets worksheet."""
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)
        all_values = worksheet.get_all_values()

        if not all_values:
            return {
                "status": "success",
                "headers": [],
                "rows": [],
                "total_rows": 0,
                "message": f"Лист '{worksheet.title}' в таблице '{sh.title}' пуст.",
            }

        headers = all_values[0]
        rows = all_values[1:]
        return {
            "status": "success",
            "table_title": sh.title,
            "sheet_name": worksheet.title,
            "headers": headers,
            "rows": rows[:100],
            "total_rows": len(rows),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_sheet_info(spreadsheet_url_or_id: str = "") -> dict:
    """Get information about a Google Sheets document (title, worksheets, sizes)."""
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheets_info = [
            {"title": ws.title, "rows": ws.row_count, "cols": ws.col_count}
            for ws in sh.worksheets()
        ]
        return {
            "status": "success",
            "document_title": sh.title,
            "spreadsheet_id": sh.id,
            "worksheets": worksheets_info,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def clear_sheet_rows(
    sheet_name: str = "Лист1",
    keep_headers: bool = False,
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Clear rows in a Google Sheet.

    Args:
        sheet_name: The name of the worksheet tab to clear (e.g. "Лист1").
        keep_headers: If True, preserves the first row (headers) and deletes only data.
                      If False, CLEARS THE ENTIRE SHEET COMPLETELY (leaves empty sheet).
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)
        all_values = worksheet.get_all_values()

        if not all_values:
            return {"status": "success", "message": f"Лист '{worksheet.title}' в таблице '{sh.title}' уже пуст."}

        if keep_headers:
            headers = all_values[0]
            deleted_count = max(0, len(all_values) - 1)
            worksheet.clear()
            if headers:
                worksheet.append_row(headers, value_input_option="USER_ENTERED")
            return {
                "status": "success",
                "message": f"В таблице '{sh.title}' лист '{worksheet.title}' очищен. Заголовки сохранены. Удалено строк: {deleted_count}",
                "rows_deleted": deleted_count,
            }
        else:
            deleted_count = len(all_values)
            worksheet.clear()
            return {
                "status": "success",
                "message": f"В таблице '{sh.title}' лист '{worksheet.title}' ПОЛНОСТЬЮ очищен. Удалено строк: {deleted_count}",
                "rows_deleted": deleted_count,
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def inspect_spreadsheet(url_or_id: str) -> dict:
    """Inspect and analyze ANY Google Sheets table by its URL or ID."""
    try:
        sheet_id = _extract_sheet_id(url_or_id)
        gc = _get_client()
        sh = gc.open_by_key(sheet_id)

        sheets_summary = []
        for ws in sh.worksheets():
            values = ws.get_all_values()
            headers = values[0] if values else []
            sample_rows = values[1:4] if len(values) > 1 else []
            sheets_summary.append({
                "title": ws.title,
                "headers": headers,
                "total_rows": max(0, len(values) - 1),
                "total_cols": len(headers),
                "sample_data": sample_rows,
            })

        return {
            "status": "success",
            "spreadsheet_id": sheet_id,
            "title": sh.title,
            "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
            "sheets_count": len(sheets_summary),
            "sheets": sheets_summary,
        }
    except gspread.exceptions.SpreadsheetNotFound:
        return {
            "status": "error",
            "message": "Таблица не найдена или к ней не выдан доступ сервисному аккаунту.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def create_spreadsheet(title: str, sheets_and_headers: str, share_email: str = "") -> dict:
    """Create a brand new Google Sheets document in Google Drive.

    Args:
        title: Title of the new Google Spreadsheet.
        sheets_and_headers: Comma-separated column headers OR JSON dict/list of sheets and headers.
        share_email: Optional email to share editor access with.
    """
    global _current_spreadsheet_id
    try:
        gc = _get_client()
        sh = gc.create(title)
        _current_spreadsheet_id = sh.id  # Make newly created sheet active immediately!

        structure: dict[str, list[str]] = {}
        try:
            parsed = json.loads(sheets_and_headers)
            if isinstance(parsed, dict):
                structure = {str(k): [str(h).strip() for h in v] for k, v in parsed.items()}
            elif isinstance(parsed, list):
                structure = {"Лист1": [str(h).strip() for h in parsed]}
        except Exception:
            headers = [h.strip() for h in sheets_and_headers.split(",") if h.strip()]
            structure = {"Лист1": headers}

        default_sheet = sh.sheet1
        first_title = list(structure.keys())[0] if structure else "Лист1"
        default_sheet.update_title(first_title)
        if structure and structure[first_title]:
            default_sheet.append_row(structure[first_title], value_input_option="USER_ENTERED")

        for sheet_name, headers in list(structure.items())[1:]:
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=max(26, len(headers)))
            if headers:
                ws.append_row(headers, value_input_option="USER_ENTERED")

        target_email = (share_email or USER_GOOGLE_EMAIL).strip()
        shared_message = ""
        if target_email:
            try:
                sh.share(target_email, perm_type="user", role="editor", notify=False)
                shared_message = f" Доступ выдан: {target_email}"
            except Exception as se:
                shared_message = f" (Ошибка выдачи доступа: {se})"

        url = f"https://docs.google.com/spreadsheets/d/{sh.id}/edit"
        return {
            "status": "success",
            "message": f"Новая таблица '{title}' успешно создана и сделана активной!{shared_message}",
            "spreadsheet_id": sh.id,
            "url": url,
            "sheets_created": list(structure.keys()),
        }
    except gspread.exceptions.APIError as ae:
        if "storage quota" in str(ae).lower():
            return {
                "status": "quota_notice",
                "message": (
                    f"Google Drive не позволяет сервисным аккаунтам создавать новые отдельные файлы на личном Google Диске (квота хранилища 0 MB). "
                    f"Но я могу создать новую таблицу-вкладку с нужными колонками прямо внутри активной таблицы! "
                    f"Используйте `create_table_sheet` для создания вкладки '{title}'."
                ),
                "suggested_action": "use_create_table_sheet",
                "table_name": title,
            }
        return {"status": "error", "message": str(ae)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def copy_data_from_spreadsheet(
    source_url_or_id: str,
    source_sheet_name: str = "",
    target_sheet_name: str = "Лист1",
    copy_headers: bool = False,
    clear_target_first: bool = False,
) -> dict:
    """Copy/import rows from ANOTHER Google Sheet into the active spreadsheet."""
    try:
        source_id = _extract_sheet_id(source_url_or_id)
        gc = _get_client()
        source_sh = gc.open_by_key(source_id)

        if source_sheet_name:
            source_ws = source_sh.worksheet(source_sheet_name)
        else:
            source_ws = source_sh.sheet1

        source_values = source_ws.get_all_values()
        if not source_values:
            return {"status": "error", "message": f"В таблице '{source_sh.title}' нет данных для копирования."}

        target_sh = _get_spreadsheet()
        try:
            target_ws = target_sh.worksheet(target_sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            target_ws = target_sh.add_worksheet(title=target_sheet_name, rows=1000, cols=26)

        if clear_target_first:
            target_ws.clear()

        if copy_headers:
            rows_to_copy = source_values
        else:
            rows_to_copy = source_values[1:] if len(source_values) > 1 else []

        if not rows_to_copy:
            return {
                "status": "success",
                "message": f"В таблице '{source_sh.title}' нет строк данных.",
                "rows_copied": 0,
            }

        target_ws.append_rows(rows_to_copy, value_input_option="USER_ENTERED")
        return {
            "status": "success",
            "message": f"Успешно скопировано {len(rows_to_copy)} строк из '{source_sh.title}' в '{target_sh.title}' -> '{target_sheet_name}'!",
            "source_title": source_sh.title,
            "target_title": target_sh.title,
            "rows_copied": len(rows_to_copy),
            "sample": rows_to_copy[:3],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def format_cells(
    range_name: str,
    sheet_name: str = "Лист1",
    bg_color: str = "",
    text_color: str = "",
    bold: bool | None = None,
    italic: bool | None = None,
    underline: bool | None = None,
    strikethrough: bool | None = None,
    font_size: int | None = None,
    font_family: str = "",
    horizontal_align: str = "",
    vertical_align: str = "",
    wrap_strategy: str = "",
    number_format_type: str = "",
    number_format_pattern: str = "",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Format cell appearance in a Google Sheet (background color, fonts, alignments, text color).

    Args:
        range_name: A1 notation range (e.g. 'A1:E1', 'B2:B20', 'A1').
        sheet_name: Name of the worksheet tab.
        bg_color: Fill color ('#4285F4', 'blue', 'синий', 'yellow', 'lightgreen', etc.).
        text_color: Font color ('#FFFFFF', 'black', 'белый', 'red', etc.).
        bold: Set bold text (True/False).
        italic: Set italic text (True/False).
        underline: Set underline (True/False).
        strikethrough: Set strikethrough (True/False).
        font_size: Font size in pt (e.g. 10, 11, 12, 14, 16, 18).
        font_family: Font name (e.g. 'Roboto', 'Arial', 'Calibri', 'Times New Roman').
        horizontal_align: 'LEFT', 'CENTER', or 'RIGHT'.
        vertical_align: 'TOP', 'MIDDLE', or 'BOTTOM'.
        wrap_strategy: 'WRAP' (перенос по словам), 'OVERFLOW', or 'CLIP'.
        number_format_type: 'CURRENCY', 'PERCENT', 'NUMBER', 'DATE', 'TIME', 'TEXT'.
        number_format_pattern: Optional custom pattern (e.g. '$#,##0.00', '0.0%').
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)

        cell_format: dict = {}

        if bg_color:
            parsed_bg = _parse_color(bg_color)
            if parsed_bg:
                cell_format["backgroundColor"] = parsed_bg

        text_format: dict = {}
        if text_color:
            parsed_fg = _parse_color(text_color)
            if parsed_fg:
                text_format["foregroundColor"] = parsed_fg
        if bold is not None:
            text_format["bold"] = bold
        if italic is not None:
            text_format["italic"] = italic
        if underline is not None:
            text_format["underline"] = underline
        if strikethrough is not None:
            text_format["strikethrough"] = strikethrough
        if font_size is not None:
            text_format["fontSize"] = font_size
        if font_family:
            text_format["fontFamily"] = font_family
        if text_format:
            cell_format["textFormat"] = text_format

        if horizontal_align:
            ha = horizontal_align.strip().upper()
            if ha in ("LEFT", "CENTER", "RIGHT"):
                cell_format["horizontalAlignment"] = ha
            elif ha in ("ПО ЦЕНТРУ", "ЦЕНТР"):
                cell_format["horizontalAlignment"] = "CENTER"
            elif ha in ("СЛЕВА", "ПО ЛЕВОМУ КРАЮ"):
                cell_format["horizontalAlignment"] = "LEFT"
            elif ha in ("СПРАВА", "ПО ПРАВОМУ КРАЮ"):
                cell_format["horizontalAlignment"] = "RIGHT"

        if vertical_align:
            va = vertical_align.strip().upper()
            if va in ("TOP", "MIDDLE", "BOTTOM"):
                cell_format["verticalAlignment"] = va

        if wrap_strategy:
            ws = wrap_strategy.strip().upper()
            if ws in ("WRAP", "OVERFLOW", "CLIP"):
                cell_format["wrapStrategy"] = ws
            elif ws in ("ПЕРЕНОС", "ПЕРЕНОСИТЬ"):
                cell_format["wrapStrategy"] = "WRAP"

        if number_format_type:
            nft = number_format_type.strip().upper()
            nf_obj: dict = {"type": nft}
            if number_format_pattern:
                nf_obj["pattern"] = number_format_pattern
            cell_format["numberFormat"] = nf_obj

        if not cell_format:
            return {"status": "error", "message": "Не указаны параметры форматирования."}

        worksheet.format(range_name, cell_format)
        return {
            "status": "success",
            "message": f"Форматирование успешно применено к диапазону '{range_name}' на листе '{worksheet.title}'.",
            "range": range_name,
            "format": cell_format,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def set_cell_borders(
    range_name: str,
    sheet_name: str = "Лист1",
    border_type: str = "ALL",
    border_style: str = "SOLID",
    border_color: str = "#000000",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Set or clear borders and frames for a cell range in Google Sheets.

    Args:
        range_name: A1 notation range (e.g. 'A1:D10', 'B2:C5').
        sheet_name: Name of the worksheet tab.
        border_type: 'ALL' (сетка: внутри и снаружи), 'OUTER' (только контур/рамка),
                     'INNER' (только внутренние перекрестья),
                     'TOP', 'BOTTOM', 'LEFT', 'RIGHT', or 'CLEAR' (убрать рамки).
        border_style: 'SOLID' (сплошная 1px), 'SOLID_MEDIUM' (жирная 2px), 'SOLID_THICK' (очень жирная),
                      'DASHED' (пунктир), 'DOTTED' (точки), 'DOUBLE' (двойная линия), 'NONE'.
        border_color: Color of the border ('#000000', 'black', 'gray', 'red', 'синий', etc.).
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)
        grid_range = gspread.utils.a1_range_to_grid_range(range_name, worksheet.id)

        btype = border_type.strip().upper()
        bstyle = border_style.strip().upper()

        if btype in ("CLEAR", "NONE", "УБРАТЬ", "ОЧИСТИТЬ") or bstyle == "NONE":
            border_spec = {"style": "NONE"}
            update_borders = {
                "range": grid_range,
                "top": border_spec,
                "bottom": border_spec,
                "left": border_spec,
                "right": border_spec,
                "innerHorizontal": border_spec,
                "innerVertical": border_spec,
            }
        else:
            parsed_color = _parse_color(border_color) or {"red": 0.0, "green": 0.0, "blue": 0.0}
            border_spec = {
                "style": bstyle if bstyle in ("SOLID", "SOLID_MEDIUM", "SOLID_THICK", "DASHED", "DOTTED", "DOUBLE") else "SOLID",
                "color": parsed_color,
            }
            update_borders = {"range": grid_range}
            if btype in ("ALL", "СЕТКА", "ВСЕ", "ВСЯ"):
                update_borders["top"] = border_spec
                update_borders["bottom"] = border_spec
                update_borders["left"] = border_spec
                update_borders["right"] = border_spec
                update_borders["innerHorizontal"] = border_spec
                update_borders["innerVertical"] = border_spec
            elif btype in ("OUTER", "КОНТУР", "РАМКА", "СНАРУЖИ"):
                update_borders["top"] = border_spec
                update_borders["bottom"] = border_spec
                update_borders["left"] = border_spec
                update_borders["right"] = border_spec
            elif btype in ("INNER", "ВНУТРИ"):
                update_borders["innerHorizontal"] = border_spec
                update_borders["innerVertical"] = border_spec
            elif btype in ("TOP", "ВЕРХ"):
                update_borders["top"] = border_spec
            elif btype in ("BOTTOM", "НИЗ"):
                update_borders["bottom"] = border_spec
            elif btype in ("LEFT", "ЛЕВО"):
                update_borders["left"] = border_spec
            elif btype in ("RIGHT", "ПРАВО"):
                update_borders["right"] = border_spec
            else:
                update_borders["top"] = border_spec
                update_borders["bottom"] = border_spec
                update_borders["left"] = border_spec
                update_borders["right"] = border_spec
                update_borders["innerHorizontal"] = border_spec
                update_borders["innerVertical"] = border_spec

        sh.batch_update({"requests": [{"updateBorders": update_borders}]})
        return {
            "status": "success",
            "message": f"Границы '{btype}' со стилем '{bstyle}' успешно установлены для '{range_name}' на листе '{worksheet.title}'.",
            "range": range_name,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def merge_or_unmerge_cells(
    range_name: str,
    action: str = "MERGE_ALL",
    sheet_name: str = "Лист1",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Merge or unmerge a range of cells in Google Sheets.

    Args:
        range_name: Range to merge/unmerge (e.g. 'A1:D1', 'A2:B5').
        action: 'MERGE_ALL' (объединить все в одну ячейку), 'MERGE_ROWS' (построчно),
                'MERGE_COLUMNS' (по столбцам), or 'UNMERGE' (разъединить обратно).
        sheet_name: Name of the worksheet tab.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)

        act = action.strip().upper()
        if act in ("UNMERGE", "РАЗЪЕДИНИТЬ", "ОТМЕНИТЬ", "РАЗОБЪЕДИНИТЬ"):
            worksheet.unmerge_cells(range_name)
            msg = f"Ячейки в диапазоне '{range_name}' успешно разъединены."
        else:
            mtype = "MERGE_ALL"
            if "ROW" in act or "СТРОК" in act:
                mtype = "MERGE_ROWS"
            elif "COL" in act or "СТОЛБ" in act:
                mtype = "MERGE_COLUMNS"
            worksheet.merge_cells(range_name, merge_type=mtype)
            msg = f"Ячейки в диапазоне '{range_name}' успешно объединены ({mtype})."

        return {"status": "success", "message": msg, "range": range_name}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def freeze_panes(
    rows: int = 1,
    cols: int = 0,
    sheet_name: str = "Лист1",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Freeze header rows and/or columns so they stay fixed while scrolling.

    Args:
        rows: Number of top rows to freeze (e.g. 1 for table header, 0 to unfreeze).
        cols: Number of left columns to freeze (e.g. 1 for first column, 0 to unfreeze).
        sheet_name: Name of the worksheet tab.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)
        worksheet.freeze(rows=rows, cols=cols)
        return {
            "status": "success",
            "message": f"Закреплено строк: {rows}, столбцов: {cols} на листе '{worksheet.title}'.",
            "frozen_rows": rows,
            "frozen_cols": cols,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def resize_dimensions(
    dimension: str = "COLUMNS",
    start_col_or_row: str = "A",
    end_col_or_row: str = "E",
    pixel_size: int = 0,
    sheet_name: str = "Лист1",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Resize column widths or row heights, or auto-fit them to content.

    Args:
        dimension: 'COLUMNS' (колонки) or 'ROWS' (строки).
        start_col_or_row: Starting column ('A', 'B', etc.) or row number ('1', '2').
        end_col_or_row: Ending column ('D', 'E', etc.) or row number ('10', '20').
        pixel_size: Pixel size (e.g. 120, 150, 200). If 0 or negative, automatically auto-fits to content!
        sheet_name: Name of the worksheet tab.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)

        dim = dimension.strip().upper()
        is_cols = dim.startswith("COL") or "СТОЛБ" in dim or "КОЛОНК" in dim

        start_idx = _col_to_index(start_col_or_row) if is_cols else int(start_col_or_row)
        end_idx = _col_to_index(end_col_or_row) if is_cols else int(end_col_or_row)

        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx

        if pixel_size <= 0:
            if is_cols:
                worksheet.columns_auto_resize(start_idx - 1, end_idx)
                msg = f"Колонки {start_col_or_row}:{end_col_or_row} автоматически подогнаны по ширине содержимого."
            else:
                worksheet.rows_auto_resize(start_idx - 1, end_idx)
                msg = f"Строки {start_col_or_row}:{end_col_or_row} автоматически подогнаны по высоте содержимого."
        else:
            req = {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": worksheet.id,
                        "dimension": "COLUMNS" if is_cols else "ROWS",
                        "startIndex": start_idx - 1,
                        "endIndex": end_idx,
                    },
                    "properties": {"pixelSize": pixel_size},
                    "fields": "pixelSize",
                }
            }
            sh.batch_update({"requests": [req]})
            unit_name = "Колонки" if is_cols else "Строки"
            msg = f"{unit_name} {start_col_or_row}:{end_col_or_row} изменены: размер установлен в {pixel_size}px."

        return {"status": "success", "message": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def manage_worksheets(
    action: str,
    sheet_name: str = "Лист1",
    new_name: str = "",
    tab_color: str = "",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Manage worksheets/tabs in Google Sheets (add, delete, rename, duplicate, change tab color).

    Args:
        action: 'add' (создать новый лист), 'delete' (удалить лист), 'rename' (переименовать),
                'duplicate' (создать копию), 'set_tab_color' (изменить цвет ярлычка).
        sheet_name: Current name of the sheet.
        new_name: New sheet name for 'add', 'rename', or 'duplicate'.
        tab_color: Color for 'set_tab_color' ('#4285F4', 'red', 'синий', etc.).
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        act = action.strip().lower()

        if act in ("add", "create", "создать", "добавить"):
            title = new_name or sheet_name or f"Лист{len(sh.worksheets()) + 1}"
            ws = sh.add_worksheet(title=title, rows=1000, cols=26)
            return {"status": "success", "message": f"Новый лист '{ws.title}' успешно создан.", "title": ws.title}

        ws = _get_worksheet(sh, sheet_name)

        if act in ("delete", "remove", "удалить"):
            title = ws.title
            sh.del_worksheet(ws)
            return {"status": "success", "message": f"Лист '{title}' успешно удален."}

        if act in ("rename", "переименовать"):
            target_title = new_name or "Лист"
            ws.update_title(target_title)
            return {"status": "success", "message": f"Лист переименован в '{target_title}'."}

        if act in ("duplicate", "copy", "дублировать", "скопировать"):
            new_title = new_name or f"Копия {ws.title}"
            new_ws = ws.duplicate(new_sheet_name=new_title)
            return {"status": "success", "message": f"Лист скопирован под именем '{new_ws.title}'."}

        if act in ("set_tab_color", "color", "цвет"):
            parsed_color = _parse_color(tab_color)
            if parsed_color:
                ws.update_tab_color(parsed_color)
                return {"status": "success", "message": f"Цвет ярлычка листа '{ws.title}' изменен."}
            else:
                ws.clear_tab_color()
                return {"status": "success", "message": f"Цвет ярлычка листа '{ws.title}' сброшен."}

        return {"status": "error", "message": f"Неизвестное действие: '{action}'."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def sort_or_filter_range(
    range_name: str,
    action: str = "sort",
    sort_column_index: int = 1,
    sort_ascending: bool = True,
    sheet_name: str = "Лист1",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Sort data in a range or enable/clear Google Sheets auto-filter.

    Args:
        range_name: Range to sort or filter (e.g. 'A2:D50', 'A1:E100').
        action: 'sort' (сортировать), 'set_filter' (включить автофильтр), 'clear_filter' (отключить фильтр).
        sort_column_index: Column number to sort by (1-indexed: 1 for A, 2 for B, etc.).
        sort_ascending: True for ascending (А-Я, 0-9), False for descending (Я-А, 9-0).
        sheet_name: Name of the worksheet tab.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)

        act = action.strip().lower()
        if act in ("sort", "сортировать", "сортировка"):
            order = "asc" if sort_ascending else "des"
            worksheet.sort((sort_column_index, order), range=range_name)
            direction_ru = "по возрастанию" if sort_ascending else "по убыванию"
            return {
                "status": "success",
                "message": f"Диапазон '{range_name}' отсортирован по колонке {sort_column_index} ({direction_ru}).",
            }
        elif act in ("set_filter", "filter", "фильтр", "включить фильтр"):
            worksheet.set_basic_filter(range_name)
            return {"status": "success", "message": f"Автофильтр успешно включен для диапазона '{range_name}'."}
        elif act in ("clear_filter", "сбросить фильтр", "отключить фильтр"):
            worksheet.clear_basic_filter()
            return {"status": "success", "message": "Автофильтр отключен."}
        else:
            return {"status": "error", "message": f"Неизвестное действие: '{action}'"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def update_cells_or_formulas(
    range_name: str,
    values: str,
    sheet_name: str = "Лист1",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Write values, formulas (e.g. '=SUM(B2:B20)', '=AVERAGE(...)', '=VLOOKUP(...)') or update specific cells.

    Args:
        range_name: A1 cell or range (e.g. 'B21', 'D2:D10', 'A1:C2').
        values: JSON array of arrays (e.g. '[[\"=SUM(B2:B20)\"]]') OR a single string/formula.
        sheet_name: Name of the worksheet tab.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)

        data_to_write = None
        try:
            parsed = json.loads(values)
            if isinstance(parsed, list):
                data_to_write = parsed
        except Exception:
            pass

        if data_to_write is None:
            val_clean = values.strip()
            if "\n" in val_clean:
                data_to_write = [[c.strip() for c in line.split(",")] for line in val_clean.splitlines() if line.strip()]
            else:
                data_to_write = [[val_clean]]

        worksheet.update(range_name=range_name, values=data_to_write, value_input_option="USER_ENTERED")
        return {
            "status": "success",
            "message": f"Данные/формулы успешно записаны в диапазон '{range_name}' на листе '{worksheet.title}'.",
            "range": range_name,
            "values": data_to_write,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def style_table_preset(
    range_name: str,
    preset: str = "MODERN_BLUE",
    freeze_header: bool = True,
    auto_fit_columns: bool = True,
    sheet_name: str = "Лист1",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Apply an all-in-one professional design preset to a table (header colors, fonts, borders, auto-width, freeze).

    Args:
        range_name: Range of the whole table (e.g. 'A1:E20').
        preset: Design palette:
                'MODERN_BLUE' (Google синий, белый жирный текст, аккуратная сетка),
                'EMERALD' (глубокий изумрудный цвет),
                'DARK_ELEGANT' (стильный темный графит),
                'WARM_CORAL' (теплый кораллово-красный),
                'MINIMAL_GRAY' (минималистичный деловой серый).
        freeze_header: Freeze the top header row (True/False).
        auto_fit_columns: Automatically fit column widths to text length (True/False).
        sheet_name: Name of the worksheet tab.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        worksheet = _get_worksheet(sh, sheet_name)

        presets = {
            "MODERN_BLUE": {"header_bg": "#1a73e8", "header_fg": "#ffffff", "border": "#4285f4", "inner_border": "#dadce0"},
            "EMERALD": {"header_bg": "#137333", "header_fg": "#ffffff", "border": "#34a853", "inner_border": "#ceead6"},
            "DARK_ELEGANT": {"header_bg": "#202124", "header_fg": "#ffffff", "border": "#5f6368", "inner_border": "#dadce0"},
            "WARM_CORAL": {"header_bg": "#d93025", "header_fg": "#ffffff", "border": "#ea4335", "inner_border": "#fad2cf"},
            "MINIMAL_GRAY": {"header_bg": "#f1f3f4", "header_fg": "#202124", "border": "#80868b", "inner_border": "#e8eaed"},
        }
        chosen = presets.get(preset.strip().upper(), presets["MODERN_BLUE"])

        grid_range = gspread.utils.a1_range_to_grid_range(range_name, worksheet.id)
        start_row = grid_range.get("startRowIndex", 0)
        end_row = grid_range.get("endRowIndex", 1)
        start_col = grid_range.get("startColumnIndex", 0)
        end_col = grid_range.get("endColumnIndex", 1)

        # 1. Format header row
        header_range = f"{gspread.utils.rowcol_to_a1(start_row + 1, start_col + 1)}:{gspread.utils.rowcol_to_a1(start_row + 1, end_col)}"
        header_format = {
            "backgroundColor": _parse_color(chosen["header_bg"]),
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "textFormat": {
                "bold": True,
                "fontSize": 11,
                "foregroundColor": _parse_color(chosen["header_fg"]),
                "fontFamily": "Roboto",
            },
            "wrapStrategy": "WRAP",
        }
        worksheet.format(header_range, header_format)

        # 2. Format data cells (if more than 1 row)
        if end_row > start_row + 1:
            data_range = f"{gspread.utils.rowcol_to_a1(start_row + 2, start_col + 1)}:{gspread.utils.rowcol_to_a1(end_row, end_col)}"
            data_format = {
                "verticalAlignment": "MIDDLE",
                "textFormat": {
                    "fontSize": 10,
                    "fontFamily": "Roboto",
                },
            }
            worksheet.format(data_range, data_format)

        # 3. Apply borders
        border_spec = {"style": "SOLID", "color": _parse_color(chosen["border"])}
        inner_spec = {"style": "SOLID", "color": _parse_color(chosen["inner_border"])}
        update_borders = {
            "range": grid_range,
            "top": border_spec,
            "bottom": border_spec,
            "left": border_spec,
            "right": border_spec,
            "innerHorizontal": inner_spec,
            "innerVertical": inner_spec,
        }
        sh.batch_update({"requests": [{"updateBorders": update_borders}]})

        # 4. Freeze header
        if freeze_header and start_row == 0:
            worksheet.freeze(rows=1)

        # 5. Auto fit columns
        if auto_fit_columns:
            worksheet.columns_auto_resize(start_col, end_col)

        return {
            "status": "success",
            "message": f"Таблица '{range_name}' успешно оформлена в стиле '{preset}' (шапка, шрифты, границы, авто-ширина).",
            "preset": preset,
            "range": range_name,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def execute_custom_sheets_request(
    requests_json: str,
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Execute raw Google Sheets API v4 batchUpdate requests for advanced features (charts, conditional formatting, banding).

    Args:
        requests_json: JSON string representing the 'requests' list in Google Sheets API v4 format.
        spreadsheet_url_or_id: Optional URL or ID of the sheet. If omitted, uses active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        parsed = json.loads(requests_json)
        req_list = parsed if isinstance(parsed, list) else [parsed]
        res = sh.batch_update({"requests": req_list})
        return {
            "status": "success",
            "message": f"Пользовательский запрос Google Sheets API успешно выполнен (выполнено команд: {len(req_list)}).",
            "replies": res.get("replies", []),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_accessible_spreadsheets() -> dict:
    """List all Google Spreadsheets that have been shared with or created by the bot on Google Drive.

    Use this when the user asks what tables exist, what tables the bot sees, or to find a table by name.
    """
    try:
        gc = _get_client()
        files = gc.list_spreadsheet_files()
        result = [
            {
                "title": f.get("name", "Без названия"),
                "id": f.get("id"),
                "url": f"https://docs.google.com/spreadsheets/d/{f.get('id')}/edit",
            }
            for f in files
        ]
        return {
            "status": "success",
            "count": len(result),
            "spreadsheets": result,
            "active_id": _current_spreadsheet_id,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def open_spreadsheet_by_name(title: str) -> dict:
    """Find and switch active spreadsheet by its document title (e.g. '2026', 'Склад', 'Отчет').

    Use this whenever the user refers to a table by its name instead of providing a full URL!
    """
    global _current_spreadsheet_id
    try:
        gc = _get_client()
        target_lower = title.strip().lower()
        files = gc.list_spreadsheet_files()
        matched = None
        for f in files:
            if f.get("name", "").strip().lower() == target_lower:
                matched = f
                break
        if not matched:
            for f in files:
                if target_lower in f.get("name", "").strip().lower():
                    matched = f
                    break
        if not matched:
            available = [f.get("name", "") for f in files]
            return {
                "status": "error",
                "message": f"Таблица с названием '{title}' не найдена среди доступных. Найденные таблицы: {available}. Если вы только что создали её, выдайте доступ сервисному аккаунту и пришлите ссылку.",
                "available_spreadsheets": available,
            }

        new_id = matched["id"]
        sh = gc.open_by_key(new_id)
        _current_spreadsheet_id = new_id
        return {
            "status": "success",
            "message": f"Активная таблица переключена на: '{sh.title}' (ID: {new_id})",
            "title": sh.title,
            "id": new_id,
            "url": f"https://docs.google.com/spreadsheets/d/{new_id}/edit",
            "sheets": [ws.title for ws in sh.worksheets()],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def rename_spreadsheet(new_title: str, spreadsheet_url_or_id: str = "") -> dict:
    """Rename the Google Spreadsheet document itself.

    Args:
        new_title: The new name for the spreadsheet document.
        spreadsheet_url_or_id: Optional URL or ID. If omitted, renames the active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        old_title = sh.title
        sh.update_title(new_title.strip())
        return {
            "status": "success",
            "message": f"Таблица успешно переименована из '{old_title}' в '{new_title}'.",
            "old_title": old_title,
            "new_title": new_title,
            "url": f"https://docs.google.com/spreadsheets/d/{sh.id}/edit",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_spreadsheet(spreadsheet_url_or_id: str = "") -> dict:
    """Delete a Google Spreadsheet document from Google Drive.

    If the service account lacks Google Drive file deletion permission (because the file is owned by your Google account),
    it safely clears all data and sheets inside the spreadsheet.

    Args:
        spreadsheet_url_or_id: Optional URL or ID. If omitted, deletes the active sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        target_id = sh.id
        title = sh.title
        gc = _get_client()
        try:
            gc.del_spreadsheet(target_id)
            return {
                "status": "success",
                "message": f"Таблица '{title}' (ID: {target_id}) успешно удалена с Google Диска.",
            }
        except gspread.exceptions.APIError:
            # If permission error (owned by user), clear all content
            for ws in sh.worksheets()[1:]:
                sh.del_worksheet(ws)
            sh.sheet1.clear()
            return {
                "status": "success",
                "message": f"В таблице '{title}' полностью удалены все листы и данные (очищена до нуля). Окончательно удалить сам пустой файл с Google Диска может владелец файла через меню Google Диска.",
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def create_table_sheet(
    sheet_name: str,
    columns: str,
    style_preset: str = "MODERN_BLUE",
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Create a new table (worksheet tab) inside the spreadsheet with columns and professional styling.

    Use this when the user says 'Создай таблицу X с колонками ...' or wants a new structured table!

    Args:
        sheet_name: Name of the new table/tab (e.g. 'Склад', 'Сотрудники', 'Продажи', 'Расходы').
        columns: Comma-separated column headers (e.g. 'ID, Товар, Количество, Цена') or JSON list.
        style_preset: Optional styling preset: 'MODERN_BLUE', 'EMERALD', 'DARK_ELEGANT', 'WARM_CORAL', 'MINIMAL_GRAY'.
        spreadsheet_url_or_id: Optional URL or ID of the sheet.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)

        col_list = []
        try:
            parsed = json.loads(columns)
            if isinstance(parsed, list):
                col_list = [str(x).strip() for x in parsed]
        except Exception:
            pass
        if not col_list:
            col_list = [c.strip() for c in columns.split(",") if c.strip()]

        if not col_list:
            col_list = ["Столбец 1", "Столбец 2", "Столбец 3"]

        ws = None
        for existing in sh.worksheets():
            if existing.title.strip().lower() == sheet_name.strip().lower():
                ws = existing
                ws.clear()
                break

        if ws is None:
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=max(26, len(col_list)))

        ws.append_row(col_list, value_input_option="USER_ENTERED")

        if style_preset:
            header_range = f"A1:{gspread.utils.rowcol_to_a1(1, len(col_list))}"
            style_table_preset(
                range_name=header_range,
                preset=style_preset,
                freeze_header=True,
                auto_fit_columns=True,
                sheet_name=ws.title,
                spreadsheet_url_or_id=sh.id,
            )

        return {
            "status": "success",
            "message": f"Новая таблица '{ws.title}' успешно создана с колонками: {', '.join(col_list)} в документе '{sh.title}'!",
            "sheet_name": ws.title,
            "columns": col_list,
            "table_title": sh.title,
            "url": f"https://docs.google.com/spreadsheets/d/{sh.id}/edit#gid={ws.id}",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_table_sheet(sheet_name: str, spreadsheet_url_or_id: str = "") -> dict:
    """Delete a table tab (worksheet) from the spreadsheet by name.

    Args:
        sheet_name: Name of the sheet tab to delete (e.g. 'Склад', 'Sheet2').
        spreadsheet_url_or_id: Optional URL or ID.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        ws = _get_worksheet(sh, sheet_name)
        title = ws.title
        if len(sh.worksheets()) <= 1:
            ws.clear()
            return {
                "status": "success",
                "message": f"Лист '{title}' был полностью очищен (Google Sheets не позволяет удалить единственный оставшийся лист в документе).",
            }
        sh.del_worksheet(ws)
        return {
            "status": "success",
            "message": f"Таблица-лист '{title}' успешно удалена из документа '{sh.title}'.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}



# ── Telegram Integration & Whitelist Management Tools ────────

def send_telegram_message(chat_id_or_username: str, text: str) -> dict:
    """Send a message to a specific Telegram chat, group, or channel.

    Use this when the user asks to send created tables, reports, or messages to a specific Telegram chat!

    Args:
        chat_id_or_username: The Telegram chat ID (e.g. -100123456789) or public username (e.g. @group_name).
        text: The text message to send (supports Markdown).
    """
    if not TELEGRAM_BOT_TOKEN:
        return {"status": "error", "message": "TELEGRAM_BOT_TOKEN не задан."}

    target = chat_id_or_username.strip()
    if not target:
        return {"status": "error", "message": "Не указан получатель (chat_id_or_username)."}

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target,
        "text": text,
        "parse_mode": "Markdown",
    }
    try:
        resp = httpx.post(url, json=payload, timeout=15.0)
        data = resp.json()
        if not data.get("ok"):
            # Retry without markdown in case of formatting syntax errors
            payload.pop("parse_mode", None)
            resp = httpx.post(url, json=payload, timeout=15.0)
            data = resp.json()

        if data.get("ok"):
            return {
                "status": "success",
                "message": f"Сообщение успешно отправлено в чат '{target}'!",
                "chat": target,
            }
        return {"status": "error", "message": f"Ошибка отправки Telegram: {data.get('description')}"}
    except Exception as e:
        return {"status": "error", "message": f"Сбой сети при отправке: {e}"}


def share_sheet_summary_to_telegram(
    chat_id_or_username: str,
    sheet_name: str = "",
    max_rows: int = 10,
    spreadsheet_url_or_id: str = "",
) -> dict:
    """Format the contents and direct link of a Google Sheet and send it directly to a Telegram chat.

    Use this to share a created or modified table with a Telegram group or user.

    Args:
        chat_id_or_username: Telegram chat ID (e.g. -100123456789) or username (e.g. @group).
        sheet_name: Name of the worksheet tab. If omitted, uses the first sheet.
        max_rows: Maximum number of rows to include in the preview table (default 10).
        spreadsheet_url_or_id: Optional spreadsheet URL or ID.
    """
    try:
        sh = _get_spreadsheet(spreadsheet_url_or_id)
        ws = _get_worksheet(sh, sheet_name) if sheet_name else sh.sheet1
        all_values = ws.get_all_values()

        url = f"https://docs.google.com/spreadsheets/d/{sh.id}/edit#gid={ws.id}"
        if not all_values:
            msg = f"""📊 **Таблица '{ws.title}'** (Документ: {sh.title})

*(Таблица пока пуста)*

🔗 [Открыть таблицу в Google Sheets]({url})"""
            return send_telegram_message(chat_id_or_username, msg)

        headers = all_values[0]
        rows = all_values[1:max_rows + 1]

        # Build clean markdown table preview
        md_lines = []
        md_lines.append("| " + " | ".join(headers) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for r in rows:
            # pad row to header length
            padded = r + [""] * (len(headers) - len(r))
            md_lines.append("| " + " | ".join(padded[:len(headers)]) + " |")

        table_md = "\n".join(md_lines)
        total_rows_note = f"\n*(Показано строк: {len(rows)} из {len(all_values) - 1})*" if len(all_values) > max_rows + 1 else ""

        full_text = f"""📊 **Таблица '{ws.title}'** в Google Таблицах:

{table_md}{total_rows_note}

🔗 [Нажмите сюда, чтобы открыть Google Таблицу]({url})"""

        return send_telegram_message(chat_id_or_username, full_text)
    except Exception as e:
        return {"status": "error", "message": f"Не удалось сформировать и отправить таблицу: {e}"}


def manage_chat_whitelist(action: str, chat_identifier: str = "") -> dict:
    """Manage the Telegram chats whitelist where the bot is allowed to respond and execute commands.

    Args:
        action: 'list' (show all allowed chats), 'add' (add chat ID or @username), 'remove' (remove chat ID or @username).
        chat_identifier: The chat ID (e.g. -100123456789) or username (@group) to add or remove.
    """
    act = action.strip().lower()
    if act == "list":
        allowed = whitelist_mgr.get_all()
        return {
            "status": "success",
            "allowed_chats": allowed,
            "count": len(allowed),
            "message": f"Разрешенные чаты ({len(allowed)}): " + (", ".join(allowed) if allowed else "[список пуст]"),
        }
    elif act == "add":
        return whitelist_mgr.add_chat(chat_identifier)
    elif act == "remove":
        return whitelist_mgr.remove_chat(chat_identifier)
    else:
        return {"status": "error", "message": f"Неизвестное действие '{action}'. Допустимо: list, add, remove."}
