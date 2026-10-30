"""Chat Filter and Request Confirmation Manager for Telegram Userbot.

Features:
  • Blacklist / Exclusion system: allows all chats EXCEPT those explicitly restricted.
  • Two-factor Confirmation store: keeps track of pending Google Sheets modification requests
    from other users awaiting the Creator's explicit approval.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

EXCLUDED_CHATS_FILE = "excluded_chats.json"
PENDING_REQUESTS_FILE = "pending_requests.json"


class ChatFilterManager:
    def __init__(
        self,
        excluded_path: str = EXCLUDED_CHATS_FILE,
        pending_path: str = PENDING_REQUESTS_FILE,
    ) -> None:
        self.excluded_path = excluded_path
        self.pending_path = pending_path
        self._excluded: set[str] = set()
        self._pending: dict[str, dict] = {}
        self._req_counter = 100

        self._load_excluded()
        self._load_pending()

    def _normalize(self, val: str | int | None) -> str:
        if val is None:
            return ""
        s = str(val).strip().lower()
        if s.startswith("@"):
            s = s[1:]
        return s

    def _load_excluded(self) -> None:
        if os.path.exists(self.excluded_path):
            try:
                with open(self.excluded_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            norm = self._normalize(item)
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

    def is_allowed(
        self,
        chat_id: int | str,
        chat_username: str | None = None,
        chat_title: str | None = None,
    ) -> bool:
        """Check if chat is allowed (i.e. NOT in the excluded/restricted list)."""
        id_norm = self._normalize(chat_id)
        if id_norm in self._excluded:
            return False

        if chat_username:
            user_norm = self._normalize(chat_username)
            if user_norm in self._excluded:
                return False

        if chat_title:
            title_norm = chat_title.strip().lower()
            for exc in self._excluded:
                if not exc:
                    continue
                # Exact title match
                if exc == title_norm:
                    return False
                # Word boundary match (e.g. "hr", "ck", "korzinka ck")
                pattern = r"(?:\b|^)" + re.escape(exc) + r"(?:\b|$)"
                if re.search(pattern, title_norm):
                    return False

        return True

    def exclude_chat(self, identifier: str) -> dict:
        """Add chat ID or username to the excluded list (stop replying there)."""
        norm = self._normalize(identifier)
        if not norm:
            return {"status": "error", "message": "Укажите ID или юзернейм чата."}

        if norm in self._excluded:
            return {"status": "info", "message": f"Чат '{identifier}' уже находится в списке исключенных."}

        self._excluded.add(norm)
        self._save_excluded()
        logger.info("Excluded chat '%s'", norm)
        return {
            "status": "success",
            "message": f"🚫 Чат '{identifier}' успешно исключен! Юзербот больше не будет в нем отвечать.",
        }

    def include_chat(self, identifier: str) -> dict:
        """Remove chat ID or username from the excluded list (allow replies again)."""
        norm = self._normalize(identifier)
        if not norm:
            return {"status": "error", "message": "Укажите ID или юзернейм чата."}

        if norm in self._excluded:
            self._excluded.remove(norm)
            self._save_excluded()
            logger.info("Re-included chat '%s'", norm)
            return {
                "status": "success",
                "message": f"✅ Чат '{identifier}' возвращен в доступ. Юзербот снова будет в нем отвечать.",
            }

        return {
            "status": "warning",
            "message": f"Чат '{identifier}' не найден в списке исключенных (он и так разрешен).",
        }

    def get_excluded(self) -> list[str]:
        """Return list of all excluded chats."""
        return sorted(list(self._excluded))

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
        """Create a new pending request waiting for Creator's approval."""
        self._req_counter += 1
        req_id = f"REQ-{self._req_counter}"
        # Fallback if already used
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
