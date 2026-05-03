"""
shared_models.py — Pydantic-схемы, общие для всех трёх сервисов.
Импортируется в main_agent, validator_service, consensus_service.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ─── Домены ──────────────────────────────────────────────────────────────────

class Domain(str, Enum):
    SCIENCE  = "science"
    TECH     = "tech"
    MEDICINE = "medicine"
    FINANCE  = "finance"
    GENERAL  = "general"


class ConsensusStrategy(str, Enum):
    MAJORITY_VOTE  = "majority_vote"
    WEIGHTED_SCORE = "weighted_score"
    TRUST_RANKING  = "trust_ranking"


# ─── Запросы ─────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    """Входящий запрос от клиента к main_agent."""
    question:      str
    user_id:       str = "user_default"
    extra_context: list[dict] = Field(default_factory=list)
    strategy:      ConsensusStrategy = ConsensusStrategy.WEIGHTED_SCORE


class ValidateRequest(BaseModel):
    """Запрос main_agent → validator_service."""
    question:   str
    domain:     Domain
    context:    list[dict] = Field(default_factory=list)
    n_validators: int = 3


class ConsensusRequest(BaseModel):
    """Запрос main_agent → consensus_service."""
    responses:  list[AgentResponse]
    strategy:   ConsensusStrategy = ConsensusStrategy.WEIGHTED_SCORE


# ─── Ответы ──────────────────────────────────────────────────────────────────

class AgentResponse(BaseModel):
    """Ответ одного валидатора."""
    agent_id:       str
    answer:         str
    confidence:     float
    trust_rank:     float = 1.0
    specialization: list[str] = Field(default_factory=list)


class AuditPayload(BaseModel):
    """Метаданные кейса, уходящие в лог."""
    agent_id:   str
    user_id:    str
    timestamp:  str
    input:      str
    output:     str
    confidence: float
    domain:     str
    context:    list[dict] = Field(default_factory=list)


class FinalAnswer(BaseModel):
    """Финальный ответ клиенту."""
    answer:          str
    confidence:      float
    source:          str          # "direct" | "AI Protocol Consensus"
    domain:          str
    strategy:        Optional[str] = None
    validators:      int = 0
    validators_used: list[str] = Field(default_factory=list)


class ConsensusResult(BaseModel):
    """Результат consensus_service."""
    answer:     str
    confidence: float
    strategy:   str


# Pydantic v2 требует rebuild для forward refs
ConsensusRequest.model_rebuild()
