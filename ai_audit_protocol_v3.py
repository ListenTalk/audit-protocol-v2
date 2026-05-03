"""
AI Audit Protocol v3 — Claude API (Anthropic)
===============================================
Что изменилось vs v2:
  - mock_generate() заменён на ClaudeEngine (реальный API)
  - confidence считается через self-consistency:
      задаём вопрос N раз → доля совпадающих ответов = confidence
  - ANTHROPIC_API_KEY читается из env (или вставить напрямую)
  - всё остальное (домены, валидаторы, консенсус, лог) без изменений

Установка:
    pip install anthropic

Запуск:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python ai_audit_protocol_v3.py
"""

import os
import json
import uuid
import random
import datetime
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

import anthropic


# ─── Конфиг ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
CLAUDE_MODEL      = "claude-sonnet-4-20250514"
CONSISTENCY_RUNS  = 3      # сколько раз спрашиваем для self-consistency
MAX_TOKENS        = 512


# ─── Claude Engine ───────────────────────────────────────────────────────────

class ClaudeEngine:
    """
    Реальный вызов Claude API.

    Confidence считается через self-consistency:
      - задаём вопрос CONSISTENCY_RUNS раз при temperature=1
      - смотрим долю совпадений с majority-ответом
      - confidence = совпадений / CONSISTENCY_RUNS

    Почему не logprobs:
      Anthropic API не отдаёт logprobs токенов (в отличие от OpenAI).
      Self-consistency — следующий лучший метод: он реально измеряет
      неопределённость модели, а не технический артефакт.
    """

    def __init__(self, api_key: str = ANTHROPIC_API_KEY):
        self.client = anthropic.Anthropic(api_key=api_key)

    def generate(
        self,
        question: str,
        context: list[dict] = None,
        system_prompt: str = None,
    ) -> tuple[str, float]:
        """
        Возвращает (ответ, confidence).
        context — список {"role": "user"|"assistant", "content": "..."}
        """
        messages = self._build_messages(question, context)
        system   = system_prompt or (
            "Ты — точный и лаконичный ассистент. "
            "Отвечай на вопрос кратко и по существу. "
            "Если не знаешь ответа — честно скажи об этом."
        )

        # Собираем CONSISTENCY_RUNS ответов
        answers = []
        for _ in range(CONSISTENCY_RUNS):
            resp = self.client.messages.create(
                model      = CLAUDE_MODEL,
                max_tokens = MAX_TOKENS,
                system     = system,
                messages   = messages,
            )
            answers.append(resp.content[0].text.strip())

        # Основной ответ = самый частый
        counter     = Counter(answers)
        best_answer, best_count = counter.most_common(1)[0]
        confidence  = round(best_count / CONSISTENCY_RUNS, 3)

        return best_answer, confidence

    def _build_messages(
        self,
        question: str,
        context: list[dict] = None,
    ) -> list[dict]:
        """Собирает messages для API из контекста + текущего вопроса."""
        messages = []
        if context:
            for msg in context[-6:]:   # последние 6 сообщений
                if msg.get("role") in ("user", "assistant"):
                    messages.append({
                        "role":    msg["role"],
                        "content": msg["content"],
                    })
        messages.append({"role": "user", "content": question})
        return messages


# ─── Домены знаний ───────────────────────────────────────────────────────────

class Domain(Enum):
    SCIENCE  = "science"
    TECH     = "tech"
    MEDICINE = "medicine"
    FINANCE  = "finance"
    GENERAL  = "general"

DOMAIN_KEYWORDS: dict[Domain, list[str]] = {
    Domain.SCIENCE:  ["физик", "химия", "астро", "квант", "антиматерия",
                      "тёмная энергия", "темная энергия", "фрактал", "молекул"],
    Domain.TECH:     ["python", "блокчейн", "нейросет", "ии", "алгоритм",
                      "программ", "код", "api", "база данных"],
    Domain.MEDICINE: ["болезн", "лечени", "вирус", "ген", "днк", "мозг", "клетк"],
    Domain.FINANCE:  ["акци", "инвест", "банк", "криптовалют", "биткоин", "экономик"],
}

# Системные промпты по доменам — валидаторы получают специализированный контекст
DOMAIN_SYSTEM_PROMPTS: dict[Domain, str] = {
    Domain.SCIENCE:  "Ты — эксперт в точных науках: физика, химия, астрономия. Отвечай точно и со ссылкой на научный консенсус.",
    Domain.TECH:     "Ты — эксперт в технологиях: программирование, ИИ, блокчейн. Давай конкретные технические ответы.",
    Domain.MEDICINE: "Ты — медицинский эксперт. Отвечай точно, при необходимости рекомендуй консультацию врача.",
    Domain.FINANCE:  "Ты — финансовый аналитик. Давай точные ответы по экономике и финансам.",
    Domain.GENERAL:  "Ты — универсальный ассистент. Отвечай честно и по существу.",
}


class DomainClassifier:
    @staticmethod
    def classify(text: str) -> Domain:
        t = text.lower()
        scores: dict[Domain, int] = {d: 0 for d in Domain}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in t:
                    scores[domain] += 1
        best = max(scores, key=scores.__getitem__)
        return best if scores[best] > 0 else Domain.GENERAL


# ─── Типы данных ─────────────────────────────────────────────────────────────

class ConsensusStrategy(Enum):
    MAJORITY_VOTE  = "majority_vote"
    WEIGHTED_SCORE = "weighted_score"
    TRUST_RANKING  = "trust_ranking"


@dataclass
class AgentResponse:
    agent_id:       str
    answer:         str
    confidence:     float
    trust_rank:     float = 1.0
    specialization: list[str] = field(default_factory=list)


@dataclass
class AuditPayload:
    agent_id:   str
    user_id:    str
    timestamp:  str
    input:      str
    output:     str
    confidence: float
    domain:     str
    context:    list[dict] = field(default_factory=list)


@dataclass
class FinalAnswer:
    answer:          str
    confidence:      float
    source:          str
    domain:          str = Domain.GENERAL.value
    strategy:        Optional[str] = None
    validators:      int = 0
    validators_used: list[str] = field(default_factory=list)


@dataclass
class CaseLog:
    payload:      AuditPayload
    final_answer: FinalAnswer
    validated:    bool


# ─── Сеть специализированных валидаторов ─────────────────────────────────────

VALIDATOR_POOL = [
    {"id": "val_science_1",  "specialization": [Domain.SCIENCE],                          "trust_rank": 0.95},
    {"id": "val_science_2",  "specialization": [Domain.SCIENCE],                          "trust_rank": 0.88},
    {"id": "val_tech_1",     "specialization": [Domain.TECH],                             "trust_rank": 0.93},
    {"id": "val_tech_2",     "specialization": [Domain.TECH],                             "trust_rank": 0.87},
    {"id": "val_medicine_1", "specialization": [Domain.MEDICINE],                         "trust_rank": 0.91},
    {"id": "val_finance_1",  "specialization": [Domain.FINANCE],                          "trust_rank": 0.89},
    {"id": "val_general_1",  "specialization": [Domain.GENERAL],                          "trust_rank": 0.75},
    {"id": "val_general_2",  "specialization": [Domain.GENERAL],                          "trust_rank": 0.70},
    {"id": "val_broad_1",    "specialization": [Domain.TECH, Domain.SCIENCE, Domain.FINANCE], "trust_rank": 0.80},
]


class ValidatorNet:
    """
    Каждый валидатор — отдельный вызов ClaudeEngine
    со специализированным system_prompt для своего домена.
    """

    def __init__(self, engine: ClaudeEngine, min_validators: int = 3):
        self.engine         = engine
        self.min_validators = min_validators

    def query(
        self,
        question: str,
        domain: Domain,
        context: list[dict] = None,
    ) -> list[AgentResponse]:

        # Выбираем специалистов
        specialists = [v for v in VALIDATOR_POOL if domain in v["specialization"]]
        if len(specialists) < self.min_validators:
            generals = [
                v for v in VALIDATOR_POOL
                if Domain.GENERAL in v["specialization"] and v not in specialists
            ]
            specialists += generals[: self.min_validators - len(specialists)]
        selected = specialists[: self.min_validators + 1]

        system_prompt = DOMAIN_SYSTEM_PROMPTS.get(domain, DOMAIN_SYSTEM_PROMPTS[Domain.GENERAL])

        responses = []
        for v in selected:
            print(f"    [{v['id']}] запрос к Claude...", flush=True)
            answer, conf = self.engine.generate(question, context, system_prompt)
            responses.append(AgentResponse(
                agent_id       = v["id"],
                answer         = answer,
                confidence     = conf,
                trust_rank     = v["trust_rank"],
                specialization = [d.value for d in v["specialization"]],
            ))

        return responses


# ─── Консенсус ───────────────────────────────────────────────────────────────

class ConsensusEngine:

    @staticmethod
    def run(
        responses: list[AgentResponse],
        strategy: ConsensusStrategy = ConsensusStrategy.WEIGHTED_SCORE,
    ) -> tuple[str, float]:

        if not responses:
            return "Консенсус недостижим.", 0.0

        if strategy == ConsensusStrategy.MAJORITY_VOTE:
            votes = Counter(r.answer for r in responses)
            best_answer, cnt = votes.most_common(1)[0]
            avg_conf = sum(r.confidence for r in responses if r.answer == best_answer) / cnt

        elif strategy == ConsensusStrategy.WEIGHTED_SCORE:
            score_map: dict[str, float] = {}
            for r in responses:
                w = r.confidence * r.trust_rank
                score_map[r.answer] = score_map.get(r.answer, 0) + w
            best_answer = max(score_map, key=score_map.__getitem__)
            total       = sum(r.confidence * r.trust_rank for r in responses)
            avg_conf    = score_map[best_answer] / total

        elif strategy == ConsensusStrategy.TRUST_RANKING:
            best         = max(responses, key=lambda r: r.trust_rank)
            best_answer  = best.answer
            avg_conf     = best.confidence

        else:
            best_answer, avg_conf = responses[0].answer, responses[0].confidence

        return best_answer, round(avg_conf, 3)


# ─── Основной агент ──────────────────────────────────────────────────────────

class MainAgent:

    CONFIDENCE_THRESHOLD = 0.60   # для real API порог чуть выше чем в mock

    def __init__(
        self,
        agent_id: str = None,
        strategy: ConsensusStrategy = ConsensusStrategy.WEIGHTED_SCORE,
        min_validators: int = 3,
        api_key: str = ANTHROPIC_API_KEY,
    ):
        self.agent_id        = agent_id or f"agent_{uuid.uuid4().hex[:8]}"
        self.strategy        = strategy
        self.engine          = ClaudeEngine(api_key)
        self.validator_net   = ValidatorNet(self.engine, min_validators)
        self.case_log: list[CaseLog] = []
        self._session_context: list[dict] = []

    # ── Публичный метод ──────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        user_id: str = "user_default",
        extra_context: list[dict] = None,
    ) -> FinalAnswer:

        context = (extra_context or []) + self._session_context
        domain  = DomainClassifier.classify(question)

        print(f"\n[MainAgent] вопрос: «{question}»")
        print(f"  domain: {domain.value} | генерирую ответ ({CONSISTENCY_RUNS} прогона)...")

        raw_answer, confidence = self.engine.generate(question, context)
        self._session_context.append({"role": "user", "content": question})

        print(f"  ответ: {raw_answer[:80]}{'...' if len(raw_answer) > 80 else ''}")
        print(f"  confidence: {confidence:.1%}")

        if confidence >= self.CONFIDENCE_THRESHOLD:
            final = FinalAnswer(
                answer     = raw_answer,
                confidence = confidence,
                source     = "direct",
                domain     = domain.value,
            )
            self._session_context.append({"role": "assistant", "content": raw_answer})
            self._log(question, raw_answer, confidence, user_id, context, domain, final, False)
            return final

        # ── Audit Protocol ───────────────────────────────────────────────────
        print(f"\n  [AuditProtocol] confidence {confidence:.1%} < {self.CONFIDENCE_THRESHOLD:.0%}")
        print(f"  Маршрутизирую к специалистам по домену «{domain.value}»...")

        payload = AuditPayload(
            agent_id   = self.agent_id,
            user_id    = user_id,
            timestamp  = datetime.datetime.now(datetime.timezone.utc).isoformat(),
            input      = question,
            output     = raw_answer,
            confidence = confidence,
            domain     = domain.value,
            context    = context[-6:],
        )

        validator_responses = self.validator_net.query(question, domain, context)
        used_ids = [r.agent_id for r in validator_responses]

        consensus_answer, consensus_conf = ConsensusEngine.run(
            validator_responses, strategy=self.strategy
        )

        print(f"  [Консенсус] confidence: {consensus_conf:.1%} | стратегия: {self.strategy.value}")

        final = FinalAnswer(
            answer          = consensus_answer,
            confidence      = consensus_conf,
            source          = "AI Protocol Consensus",
            domain          = domain.value,
            strategy        = self.strategy.value,
            validators      = len(validator_responses),
            validators_used = used_ids,
        )

        self._session_context.append({"role": "assistant", "content": consensus_answer})
        self._log(question, raw_answer, confidence, user_id, context, domain, final, True, payload)
        return final

    def reset_context(self):
        self._session_context = []

    # ── Лог ──────────────────────────────────────────────────────────────────

    def _log(self, question, raw_answer, confidence, user_id,
             context, domain, final, validated, payload=None):
        if payload is None:
            payload = AuditPayload(
                agent_id   = self.agent_id,
                user_id    = user_id,
                timestamp  = datetime.datetime.now(datetime.timezone.utc).isoformat(),
                input      = question,
                output     = raw_answer,
                confidence = confidence,
                domain     = domain.value,
                context    = context[-6:],
            )
        self.case_log.append(CaseLog(
            payload      = payload,
            final_answer = final,
            validated    = validated,
        ))

    def export_log(self) -> str:
        return json.dumps(
            [asdict(c) for c in self.case_log],
            ensure_ascii=False, indent=2
        )


# ─── Демо ────────────────────────────────────────────────────────────────────

def print_result(result: FinalAnswer):
    print(f"\n{'─'*60}")
    print(f"Ответ      : {result.answer[:120]}{'...' if len(result.answer) > 120 else ''}")
    print(f"Домен      : {result.domain}")
    print(f"Уверенность: {result.confidence:.1%}")
    print(f"Источник   : {result.source}", end="")
    if result.strategy:
        print(f"  [{result.strategy}, {result.validators} val]", end="")
    print()


if __name__ == "__main__":

    # ── Проверка ключа ───────────────────────────────────────────────────────
    if ANTHROPIC_API_KEY == "YOUR_API_KEY_HERE":
        print("⚠️  Вставь API ключ: export ANTHROPIC_API_KEY='sk-ant-...'")
        print("   Или замени строку ANTHROPIC_API_KEY в начале файла.\n")
        print("   Для теста без ключа используй ai_audit_protocol_v2.py (mock-версия).")
        exit(1)

    agent = MainAgent(
        agent_id       = "main_agent_001",
        strategy       = ConsensusStrategy.WEIGHTED_SCORE,
        min_validators = 3,
    )

    questions = [
        "Что такое Python и для чего его используют?",
        "Объясни принцип работы квантового компьютера",
        "Как работает блокчейн в двух словах?",
    ]

    print("=" * 60)
    print(f"AI Audit Protocol v3 | модель: {CLAUDE_MODEL}")
    print(f"self-consistency runs: {CONSISTENCY_RUNS} | порог: {MainAgent.CONFIDENCE_THRESHOLD:.0%}")
    print("=" * 60)

    for q in questions:
        result = agent.ask(q, user_id="demo_user")
        print_result(result)

    # Экспорт лога
    print(f"\n{'═'*60}")
    print("Лог (JSON):")
    print(agent.export_log())
