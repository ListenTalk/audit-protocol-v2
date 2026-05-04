def critique(engine, answer):

    prompt = f"""
Ответ:
{answer}

Есть ли ошибки? Ответь OK или FIX
"""

    res = engine.generate(prompt, "Ты критик.")

    return "FIX" in res.upper()
