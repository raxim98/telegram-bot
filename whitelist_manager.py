"""Whitelist Manager for Telegram Chats.

Manages dynamic persistent storage of allowed chats/groups/channels.
Supports Telegram numeric IDs (e.g. -100123456789) and usernames (e.g. @my_group).
"""

from __future__ import annotations

import json
import logging
import os
from config import ALLOWED_CHATS, ALLOWED_CHATS_FILE

logger = logging.getLogger(__name__)


class WhitelistManager:
    def __init__(self, filepath: str = ALLOWED_CHATS_FILE) -> None:
        self.filepath = filepath
        self._allowed_chats: set[str] = set()
        self._load()

    def _normalize(self, val: str | int | None) -> str:
        if val is None:
            return ""
        s = str(val).strip().lower()
        if s.startswith("@"):
            s = s[1:]
        return s

    def _load(self) -> None:
        # 1. Seed from config.ALLOWED_CHATS
        for c in ALLOWED_CHATS:
            norm = self._normalize(c)
            if norm:
                self._allowed_chats.add(norm)

        # 2. Load from JSON file if exists
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            norm = self._normalize(item)
                            if norm:
                                self._allowed_chats.add(norm)
            except Exception as e:
                logger.error("Error loading %s: %s", self.filepath, e)

        # Save merged list
        self._save()

    def _save(self) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self._allowed_chats)), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Error saving %s: %s", self.filepath, e)

    def is_chat_allowed(self, chat_id: int | str, chat_username: str | None = None) -> bool:
        """Check if a chat ID or username is in the allowed whitelist."""
        if not self._allowed_chats:
            return False

        # Check numeric/string chat ID
        id_norm = self._normalize(chat_id)
        if id_norm in self._allowed_chats:
            return True

        # Check username if provided
        if chat_username:
            user_norm = self._normalize(chat_username)
            if user_norm in self._allowed_chats:
                return True

        return False

    def add_chat(self, identifier: str) -> dict:
        """Add a chat ID or username to the whitelist."""
        norm = self._normalize(identifier)
        if not norm:
            return {"status": "error", "message": "Пустой идентификатор чата."}

        if norm in self._allowed_chats:
            return {"status": "info", "message": f"Чат '{identifier}' уже находится в списке разрешенных."}

        self._allowed_chats.add(norm)
        self._save()
        logger.info("Added chat '%s' to whitelist", norm)
        return {"status": "success", "message": f"Чат '{identifier}' успешно добавлен в список разрешенных!"}

    def remove_chat(self, identifier: str) -> dict:
        """Remove a chat ID or username from the whitelist."""
        norm = self._normalize(identifier)
        if not norm:
            return {"status": "error", "message": "Пустой идентификатор чата."}

        if norm in self._allowed_chats:
            self._allowed_chats.remove(norm)
            self._save()
            logger.info("Removed chat '%s' from whitelist", norm)
            return {"status": "success", "message": f"Чат '{identifier}' удален из списка разрешенных."}

        return {"status": "warning", "message": f"Чат '{identifier}' не был найден в списке разрешенных."}

    def get_all(self) -> list[str]:
        """Return sorted list of all whitelisted chat identifiers."""
        return sorted(list(self._allowed_chats))


# Singleton instance
whitelist_mgr = WhitelistManager()
