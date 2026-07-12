from __future__ import annotations

import json
import os
import re
from pathlib import Path


PREFERENCE_PATTERNS = {
    "liquidity risk": r"\bliquidity(?:\s+risk)?\b|流动性风险",
    "debt maturity": r"\bdebt maturit(?:y|ies)\b|债务到期",
    "cash flow": r"\bcash flow\b|现金流",
    "profitability": r"\bprofitability\b|\bmargin\b|盈利能力|利润率",
    "competition": r"\bcompetition\b|竞争",
    "valuation": r"\bvaluation\b|估值",
}
ALLOWED_PREFERENCES = frozenset(PREFERENCE_PATTERNS)
USER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}\Z")


class PreferenceStore:
    """A deliberately small, inspectable long-term memory scoped to user ID."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, user_id: str) -> list[str]:
        self._validate_user_id(user_id)
        data = self._load()
        return list(data.get(user_id, []))

    def record(self, user_id: str, message: str) -> list[str]:
        self._validate_user_id(user_id)
        lowered = message.lower()
        intent = re.search(r"\b(i care|focus|prefer|priority|important to me|i'?m interested in|i am interested in|interested in)\b|关注|重视|偏好|感兴趣", lowered, re.IGNORECASE)
        if not intent:
            return self.get(user_id)
        found = sorted(name for name, pattern in PREFERENCE_PATTERNS.items() if re.search(pattern, lowered, re.IGNORECASE))
        if not found:
            return self.get(user_id)
        data = self._load()
        merged = sorted(set(data.get(user_id, [])) | set(found))
        data[user_id] = merged
        self._write(data)
        return merged

    def set(self, user_id: str, preferences: list[str]) -> list[str]:
        """Replace one user's preferences with an explicit, auditable whitelist."""
        self._validate_user_id(user_id)
        normalized = self._validate_preferences(preferences)
        data = self._load()
        if normalized:
            data[user_id] = normalized
        else:
            data.pop(user_id, None)
        self._write(data)
        return normalized

    def remove(self, user_id: str, preferences: list[str]) -> list[str]:
        self._validate_user_id(user_id)
        removed = set(self._validate_preferences(preferences))
        remaining = sorted(set(self.get(user_id)) - removed)
        return self.set(user_id, remaining)

    def clear(self, user_id: str) -> bool:
        """Delete all persisted memory for one user without affecting other users."""
        self._validate_user_id(user_id)
        data = self._load()
        existed = user_id in data
        if existed:
            del data[user_id]
            self._write(data)
        return existed

    def _load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            user_id: sorted(value for value in preferences if value in ALLOWED_PREFERENCES)
            for user_id, preferences in data.items()
            if isinstance(user_id, str) and USER_ID_RE.fullmatch(user_id) and isinstance(preferences, list)
        }

    @staticmethod
    def _validate_user_id(user_id: str) -> None:
        if not isinstance(user_id, str) or not USER_ID_RE.fullmatch(user_id):
            raise ValueError("User ID must be 1-64 characters using letters, numbers, '.', '_', '@', or '-'")

    @staticmethod
    def _validate_preferences(preferences: list[str]) -> list[str]:
        if not isinstance(preferences, list) or any(not isinstance(item, str) for item in preferences):
            raise ValueError("Preferences must be a list of supported topic names")
        normalized = sorted(set(preferences))
        unsupported = set(normalized) - ALLOWED_PREFERENCES
        if unsupported:
            raise ValueError(f"Unsupported preference topics: {', '.join(sorted(unsupported))}")
        return normalized

    def _write(self, data: dict[str, list[str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
