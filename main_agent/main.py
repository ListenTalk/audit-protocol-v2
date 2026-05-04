import uuid
from audit_protocol_v5.engine import Engine
from audit_protocol_v5.memory import Memory
from audit_protocol_v5.critique import critique

# если у тебя есть эти сервисы — оставь импорты
# если названия отличаются — подправь пути
try:
    from validator_service.main import run_validators
except:
    run_validators = None

try:
    from consensus_service.main import run_consensus
except:
    run_consensus = None


class MainAgent:

    THRESHOLD = 0.65

    def __init__(self):
        self.engine = Engine()
        self.memory = Memory()

    def ask(self, question: str):

        request_id = uuid.uuid4().hex[:8]
        print(f"\n[{request_id}] Q: {question}")

        # ─── MEMORY ─────────────────────────
        past_answers = self.memory.search(question)
        context = "\n".join(past_answers)

        system = f"""
Используй контекст если он релевантен:
{context}
"""

        # ─── BASE GENERATION ────────────────
        answer = self.engine.generate(question, system)

        print(f"base: {answer[:100]}")

        # ─── CRITIQUE LOOP ─────────────────
        need_fix = critique(self.engine, answer)

        if need_fix:
            print("→ critique triggered")

            if run_validators and run_consensus:

                # ─── VALIDATORS ─────────────
                responses = run_validators(question)

                # ожидается формат:
                # [{"answer": str, "confidence": float, "trust": float}, ...]

                # ─── CONSENSUS ──────────────
                final_answer, final_conf = run_consensus(responses)

                print(f"consensus: {final_answer[:100]}")
                print(f"confidence: {final_conf}")

            else:
                print("⚠️ validators/consensus не подключены")
                final_answer = answer
                final_conf = 0.5

        else:
            final_answer = answer
            final_conf = 0.8

        # ─── MEMORY SAVE ───────────────────
        self.memory.add(question, final_answer)

        print(f"final: {final_answer[:100]}")
        print(f"final confidence: {final_conf}")
        print(f"cost: {self.engine.cost:.5f}")

        return {
            "answer": final_answer,
            "confidence": final_conf
        }


# ─
