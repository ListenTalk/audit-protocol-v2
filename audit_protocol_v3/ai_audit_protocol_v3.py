import os
import uuid
import time
import json
import asyncio
import random
import datetime
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Optional

import anthropic

# ─── CONFIG ─────────────────────────────────────

API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL   = "claude-sonnet-4-20250514"

CONSISTENCY_RUNS = 3
MAX_TOKENS = 512
TIMEOUT = 30

# ─── UTILS ─────────────────────────────────────

def normalize(text: str) -> str:
    return text.lower().strip().replace(".", "").replace(",", "")

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

# ─── ENGINE (ASYNC + CACHE + RETRY) ─────────────────────────

class ClaudeEngine:

    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.cache = {}

    async def _call(self, messages, system):
        return await self.client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        )

    async def safe_call(self, messages, system, retries=3):
        for i in range(retries):
            try:
                return await self._call(messages, system)
            except Exception:
                if i == retries - 1:
                    raise
                await asyncio.sleep(2 ** i)

    async def generate(self, question, system):

        cache_key = (question, system)
        if cache_key in self.cache:
            return self.cache[cache_key]

        messages = [{"role": "user", "content": question}]
        answers = []

        for i in range(CONSISTENCY_RUNS):
            resp = await self.safe_call(messages, system)
            text = resp.content[0].text.strip()
            answers.append(text)

            # 🔥 ранний выход
            if len(answers) >= 2:
                counter = Counter(map(normalize, answers))
                best, count = counter.most_common(1)[0]
                if count / len(answers) >= 0.9:
                    result = (answers[-1], round(count / len(answers), 3))
                    self.cache[cache_key] = result
                    return result

        counter = Counter(map(normalize, answers))
        best_norm, best_count = counter.most_common(1)[0]

        best_answer = next(a for a in answers if normalize(a) == best_norm)
        confidence = round(best_count / len(answers), 3)

        result = (best_answer, confidence)
        self.cache[cache_key] = result
        return result


# ─── DATA ─────────────────────────────────────

@dataclass
class AgentResponse:
    agent_id: str
    answer: str
    confidence: float
    trust: float


@dataclass
class FinalAnswer:
    answer: str
    confidence: float
    source: str
    validators: int = 0


# ─── VALIDATORS ─────────────────────────────────

VALIDATORS = [
    {"id": "v1", "trust": 0.95},
    {"id": "v2", "trust": 0.9},
    {"id": "v3", "trust": 0.85},
    {"id": "v4", "trust": 0.8},
]

class ValidatorNet:

    def __init__(self, engine):
        self.engine = engine

    async def query(self, question):

        tasks = []

        for v in VALIDATORS:
            persona = f"""
Ты валидатор {v['id']}.
Будь критичным. Если не уверен — укажи это.
"""

            system = "Ты эксперт. Отвечай кратко.\n" + persona

            tasks.append(self.engine.generate(question, system))

        results = await asyncio.gather(*tasks)

        responses = []
        for (answer, conf), v in zip(results, VALIDATORS):
            responses.append(AgentResponse(
                agent_id=v["id"],
                answer=answer,
                confidence=conf,
                trust=v["trust"]
            ))

        return responses


# ─── CONSENSUS (УЛУЧШЕННЫЙ) ─────────────────────

class Consensus:

    @staticmethod
    def run(responses):

        score_map = {}
        answers = []

        for r in responses:
            norm = normalize(r.answer)
            weight = r.confidence * r.trust

            score_map[norm] = score_map.get(norm, 0) + weight
            answers.append(norm)

        best = max(score_map, key=score_map.get)

        # 🔥 штраф за disagreement
        variance = len(set(answers)) / len(answers)

        total = sum(score_map.values())
        confidence = score_map[best] / total

        confidence *= (1 - variance)

        best_answer = next(r.answer for r in responses if normalize(r.answer) == best)

        return best_answer, round(confidence, 3)


# ─── MAIN AGENT ─────────────────────────────────

class MainAgent:

    THRESHOLD = 0.65

    def __init__(self):
        self.engine = ClaudeEngine(API_KEY)
        self.validators = ValidatorNet(self.engine)

    async def ask(self, question):

        request_id = uuid.uuid4().hex
        start = time.time()

        print(f"\n[{request_id}] Q: {question}")

        system = "Ты точный ассистент."

        answer, conf = await self.engine.generate(question, system)

        print(f"  base confidence: {conf}")

        if conf >= self.THRESHOLD:
            return FinalAnswer(answer, conf, "direct")

        print("  → audit triggered")

        responses = await self.validators.query(question)

        final_answer, final_conf = Consensus.run(responses)

        latency = time.time() - start

        print(f"  final confidence: {final_conf} | latency: {latency:.2f}s")

        return FinalAnswer(
            answer=final_answer,
            confidence=final_conf,
            source="consensus",
            validators=len(responses)
        )


# ─── RUN ─────────────────────────────────────

async def main():

    agent = MainAgent()

    questions = [
        "Что такое Python?",
        "Как работает блокчейн?",
        "Объясни квантовый компьютер"
    ]

    for q in questions:
        result = await agent.ask(q)

        print("—" * 50)
        print("Ответ:", result.answer[:100])
        print("Confidence:", result.confidence)
        print("Source:", result.source)


if __name__ == "__main__":
    asyncio.run(main())
