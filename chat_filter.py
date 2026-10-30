"""Chat Filter and Request Confirmation Manager for Telegram Userbot.

Features:
  • Dual-mode Filtering:
      - Whitelist Mode (Default): Userbot ONLY replies to specifically allowed chats/users
        (Sevara, Onam, Сайдамир, хasanovich.11, Komol, Доклады Боймуратов Р,Р, Ойбек ака,
         СК Группа, ходиев мирориф). All other chats are completely ignored.
      - Blacklist Mode: Userbot replies everywhere EXCEPT in explicitly excluded chats.
  • Dynamic In-chat & Saved Messages commands to allow/disallow chats at any time.
  • Two-factor Confirmation store for Google Sheets modification requests.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

EXCLUDED_CHATS_FILE = "excluded_chats.json"
ALLOWED_CHATS_FILE = "userbot_allowed_chats.json"
SETTINGS_FILE = "userbot_settings.json"
PENDING_REQUESTS_FILE = "pending_requests.json"

# Default whitelist requested by creator
DEFAULT_ALLOWED_CHATS = [
    "sevara", "севара",
    "onam", "онам",
    "сайдамир", "saydamir",
    "хasanovich.11", "xasanovich.11", "xasanovich_11", "xasanovich",
    "komol", "комол",
    "доклады боймуратов р,р", "доклады боймуратов р.р", "доклады боймуратов", "боймуратов",
    "ходиев мирориф", "ходиев", "мирориф",
]

# Homoglyph mapping to unify Latin and Cyrillic
HOMOGLYPHS = {
    "c": "с", "x": "х", "a": "а", "e": "е", "o": "о",
    "p": "р", "k": "к", "m": "м", "t": "т", "b": "в", "y": "у",
}


def normalize_string(text: str | int | None) -> str:
    """Normalize text with punctuation stripping, homoglyph mapping, and lowercasing."""
    if text is None:
        return ""
    s = str(text).strip().lower()
    if s.startswith("@"):
        s = s[1:]
    # Replace separators with a single space
    s = re.sub(r"[\.,_\-\/\\\|\(\)\u2764\ufe0f]+", " ", s)
    chars = [HOMOGLYPHS.get(ch, ch) for ch in s]
    return re.sub(r"\s+", " ", "".join(chars)).strip()


class ChatFilterManager:
    def __init__(
        self,
        excluded_path: str = EXCLUDED_CHATS_FILE,
        allowed_path: str = ALLOWED_CHATS_FILE,
        settings_path: str = SETTINGS_FILE,
        pending_path: str = PENDING_REQUESTS_FILE,
    ) -> None:
        self.excluded_path = excluded_path
        self.allowed_path = allowed_path
        self.settings_path = settings_path
        self.pending_path = pending_path

        self._excluded: set[str] = set()
        self._allowed: set[str] = set()
        self.whitelist_mode: bool = True  # Strict whitelist mode enabled by default
        self._pending: dict[str, dict] = {}
        self._req_counter = 100

        self._load_settings()
        self._load_excluded()
        self._load_allowed()
        self._load_pending()

    def _load_settings(self) -> None:
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.whitelist_mode = data.get("whitelist_mode", True)
            except Exception as e:
                logger.error("Error loading %s: %s", self.settings_path, e)
        else:
            self._save_settings()

    def _save_settings(self) -> None:
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump({"whitelist_mode": self.whitelist_mode}, f, indent=2)
        except Exception as e:
            logger.error("Error saving %s: %s", self.settings_path, e)

    def _load_allowed(self) -> None:
        # Seed with default allowed chats
        for item in DEFAULT_ALLOWED_CHATS:
            norm = normalize_string(item)
            if norm:
                self._allowed.add(norm)

        if os.path.exists(self.allowed_path):
            try:
                with open(self.allowed_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            norm = normalize_string(item)
                            if norm:
                                self._allowed.add(norm)
            except Exception as e:
                logger.error("Error loading %s: %s", self.allowed_path, e)
        self._save_allowed()

    def _save_allowed(self) -> None:
        try:
            with open(self.allowed_path, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self._allowed)), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Error saving %s: %s", self.allowed_path, e)

    def _load_excluded(self) -> None:
        if os.path.exists(self.excluded_path):
            try:
                with open(self.excluded_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            norm = normalize_string(item)
                            if norm:
                                self._excluded.add(norm)
            except Exception as e:
                logger.error("Error loading %s: %s", self.excluded_path, e)
        self._save_excluded()

    def _save_excluded(self) -> None:
        try:
            with open(self.excluded_path, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self._excluded)), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Error saving %s: %s", self.excluded_path, e)

    def _load_pending(self) -> None:
        if os.path.exists(self.pending_path):
            try:
                with open(self.pending_path, "r", encoding="utf-8") as f:
                    self._pending = json.load(f)
            except Exception as e:
                logger.error("Error loading %s: %s", self.pending_path, e)

    def _save_pending(self) -> None:
        try:
            with open(self.pending_path, "w", encoding="utf-8") as f:
                json.dump(self._pending, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Error saving %s: %s", self.pending_path, e)

    # ── Matching Core ─────────────────────────────────────────

    def _matches_target(self, pattern: str, chat_id: int | str, chat_username: str | None, chat_title: str | None) -> bool:
        """Check if a pattern matches chat ID, username, or title."""
        norm_pat = normalize_string(pattern)
        if not norm_pat:
            return False

        # 1. Match numeric ID
        id_norm = normalize_string(chat_id)
        if norm_pat == id_norm:
            return True

        # 2. Match username
        if chat_username:
            user_norm = normalize_string(chat_username)
            if norm_pat == user_norm or norm_pat in user_norm:
                return True

        # 3. Match title / contact name
        if chat_title:
            title_norm = normalize_string(chat_title)
            if norm_pat == title_norm or norm_pat in title_norm:
                return True

            # Match all individual words in pattern regardless of word order
            pat_words = [w for w in norm_pat.split() if len(w) > 1]
            if len(pat_words) > 1 and all(w in title_norm for w in pat_words):
                return True

            # Stem match ONLY for single-word names >= 5 chars (e.g. sevara -> sevar in sevarka)
            if len(pat_words) == 1 and len(norm_pat) >= 5 and norm_pat[:5] in title_norm:
                return True

        return False

    def is_allowed(
        self,
        chat_id: int | str,
        chat_username: str | None = None,
        chat_title: str | None = None,
    ) -> bool:
        """Check if userbot is allowed to reply in this chat."""
        # 0. Always check excluded list FIRST (blacklist has highest priority)
        for pattern in self._excluded:
            if self._matches_target(pattern, chat_id, chat_username, chat_title):
                return False

        # 1. Strict Whitelist Mode
        if self.whitelist_mode:
            for pattern in self._allowed:
                if self._matches_target(pattern, chat_id, chat_username, chat_title):
                    return True
            # In whitelist mode, if not in allowed list, ignore completely
            return False

        return True

    # ── Chat Inclusion / Exclusion Management ──────────────────

    def include_chat(self, identifier: str) -> dict:
        """Add chat to allowed list (or remove from excluded list)."""
        norm = normalize_string(identifier)
        if not norm:
            return {"status": "error", "message": "Укажите название, ID или юзернейм чата."}

        self._allowed.add(norm)
        self._save_allowed()

        if norm in self._excluded:
            self._excluded.remove(norm)
            self._save_excluded()

        logger.info("Chat '%s' added to allowed list.", norm)
        return {
            "status": "success",
            "message": f"✅ Чат '{identifier}' добавлен в список разрешенных. Юзербот будет отвечать в нем.",
        }

    def exclude_chat(self, identifier: str) -> dict:
        """Remove chat from allowed list (or add to excluded list)."""
        norm = normalize_string(identifier)
        if not norm:
            return {"status": "error", "message": "Укажите название, ID или юзернейм чата."}

        if norm in self._allowed:
            self._allowed.remove(norm)
            self._save_allowed()

        self._excluded.add(norm)
        self._save_excluded()

        logger.info("Chat '%s' excluded from replies.", norm)
        return {
            "status": "success",
            "message": f"🚫 Чат '{identifier}' исключен. Юзербот больше НЕ будет отвечать в нем.",
        }

    def get_allowed(self) -> list[str]:
        """Return list of allowed chats."""
        return sorted(list(self._allowed))

    def get_excluded(self) -> list[str]:
        return sorted(list(self._excluded))

    def set_whitelist_mode(self, enabled: bool) -> None:
        self.whitelist_mode = enabled
        self._save_settings()

    # ── Pending Requests (Confirmation Workflow) ─────────────

    def create_pending_request(
        self,
        chat_id: int,
        chat_title: str,
        sender_name: str,
        sender_id: int,
        original_text: str,
        action_summary: str,
        reply_to_msg_id: int | None = None,
    ) -> str:
        self._req_counter += 1
        req_id = f"REQ-{self._req_counter}"
        while req_id in self._pending:
            self._req_counter += 1
            req_id = f"REQ-{self._req_counter}"

        self._pending[req_id] = {
            "req_id": req_id,
            "chat_id": chat_id,
            "chat_title": chat_title,
            "sender_name": sender_name,
            "sender_id": sender_id,
            "original_text": original_text,
            "action_summary": action_summary,
            "reply_to_msg_id": reply_to_msg_id,
            "created_at": time.time(),
        }
        self._save_pending()
        logger.info("Created pending request %s for chat %s", req_id, chat_id)
        return req_id

    def get_pending_request(self, req_id: str) -> dict | None:
        return self._pending.get(req_id.upper().strip())

    def pop_pending_request(self, req_id: str) -> dict | None:
        req = self._pending.pop(req_id.upper().strip(), None)
        if req:
            self._save_pending()
        return req

    def list_pending(self) -> list[dict]:
        return list(self._pending.values())


# Singleton instance
chat_filter_mgr = ChatFilterManager()
