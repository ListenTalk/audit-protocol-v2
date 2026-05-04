import anthropic
import os
import time

API_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL_PRIMARY = "claude-sonnet-4-20250514"
MODEL_FALLBACK = "claude-3-haiku-20240307"


class Engine:

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=API_KEY)
        self.cost = 0

    def generate(self, question, system):

        try:
            resp = self.client.messages.create(
                model=MODEL_PRIMARY,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": question}],
            )
        except Exception:
            resp = self.client.messages.create(
                model=MODEL_FALLBACK,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": question}],
            )

        text = resp.content[0].text.strip()

        tokens = getattr(resp, "usage", {}).output_tokens if hasattr(resp, "usage") else 0
        self.cost += tokens * 0.00001

        return text
