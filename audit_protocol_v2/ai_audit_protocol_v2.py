"""
AI Audit Protocol v2 (mock version)
==================================
Базовая версия без реального API.
Использует случайные ответы и confidence.
"""

import random
import uuid
from collections import Counter
from dataclasses import dataclass


# ─── MOCK GENERATOR ─────────────────────────

def mock_generate(question: str):
    fake_answers = [
        "Это язык программирования высокого уровня.",
        "Это технология распределённого реестра.",
        "Это сложная вычислительная система.",
        "Это метод обработки данных.",
    ]
    answer = random.choice(fake_answers)
    confidence = round(random.uniform(0.4, 0.95), 2)
    return answer, confidence


# ─── DATA ───────────────────────────────────

@dataclass
class Response:
    agent_id: str
    answer: str
    confidence: float


# ─── VALIDATORS ─────────────────────────────

def run_validators(question, n=3):
    responses = []
    for i in range(n):
        ans, conf = mock_generate(question)
        responses.append(Response(
            agent_id=f"validator_{i}",
            answer=ans,
            confidence=conf
        ))
    return responses


# ─── CONSENSUS ──────────────────────────────

def consensus(responses):
    votes = Counter(r.answer for r in responses)
    best_answer, count = votes.most_common(1)[0]

    avg_conf = sum(r.confidence for r in responses if r.answer == best_answer) / count

    return best_answer, round(avg_conf, 2)


# ─── MAIN AGENT ─────────────────────────────

class Agent:

    THRESHOLD = 0.6

    def __init__(self):
        self.id = f"agent_{uuid.uuid4().hex[:6]}"

    def ask(self, question):

        print(f"\nQ: {question}")

        answer, conf = mock_generate(question)

        print(f"base: {answer}")
        print(f"confidence: {conf}")

        if conf >= self.THRESHOLD:
            print("→ direct answer")
            return answer

        print("→ audit triggered")

        responses = run_validators(question)
        final, final_conf = consensus(responses)

        print(f"final: {final}")
        print(f"final confidence: {final_conf}")

        return final


# ─── RUN ────────────────────────────────────

if __name__ == "__main__":

    agent = Agent()

    questions = [
        "Что такое Python?",
        "Как работает блокчейн?",
        "Объясни ИИ"
    ]

    for q in questions:
        agent.ask(q)
