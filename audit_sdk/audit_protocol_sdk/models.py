"""
audit_protocol_sdk/models.py
==============================
Pydantic-модели SDK: входящие запросы и исходящие ответы.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ConsensusStrategy(str, Enum):
    MAJORITY_VOTE  = "majority_vote"
    WEIGHTED_SCORE = "weighted_score"
    TRUST_RANKING  = "trust_ranking"


class AskRequest(BaseModel):
    question:      str
    user_id:       str = "sdk_user"
    strategy:      ConsensusStrategy = ConsensusStrategy.WEIGHTED_SCORE
    extra_context: list[dict] = Field(default_factory=list)


class Reply(BaseModel):
    """Ответ протокола — то что получает пользователь SDK."""

    answer:          str
    confidence:      float
    source:          str            # "direct" | "AI Protocol Consensus"
    domain:          str            # "tech" | "science" | "medicine" | ...
    validated:       bool           # True если прошёл через консенсус
    strategy:        Optional[str]  # стратегия консенсуса (если validated)
    validators:      int            # кол-во валидаторов (если validated)
    validators_used: list[str]      # id валидаторов (если validated)

    def __str__(self) -> str:
        badge = "✓ consensus" if self.validated else "→ direct"
        return (
            f"[{badge} | {self.confidence:.0%} | {self.domain}] "
            f"{self.answer}"
        )

    def is_confident(self, threshold: float = 0.6) -> bool:
        """Вернуть True если уверенность выше порога."""
        return self.confidence >= threshold

    def summary(self) -> str:
        """Краткая сводка для логирования."""
        lines = [
            f"Ответ      : {self.answer[:100]}{'...' if len(self.answer) > 100 else ''}",
            f"Уверенность: {self.confidence:.1%}",
            f"Источник   : {self.source}",
            f"Домен      : {self.domain}",
        ]
        if self.validated:
            lines.append(
                f"Валидаторы : {self.validators} "
                f"({', '.join(self.validators_used)})"
            )
        return "\n".join(lines)
