FROM python:3.12

WORKDIR /app

# копируем ВЕСЬ проект
COPY . /app

# зависимости
RUN pip install --no-cache-dir anthropic uvicorn fastapi

# запуск
CMD ["python", "main_agent/main.py"]
