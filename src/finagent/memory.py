from __future__ import annotations

import json
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


class PreferenceStore:
    """A deliberately small, inspectable long-term memory scoped to user ID."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, user_id: str) -> list[str]:
        data = self._load()
        return list(data.get(user_id, []))

    def record(self, user_id: str, message: str) -> list[str]:
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged

    def _load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}
