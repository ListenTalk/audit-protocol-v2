FROM python:3.12-slim

WORKDIR /app

# зависимости отдельным слоем — кешируются при rebuild
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# исходники
COPY shared_models.py .
COPY main_agent/       main_agent/
COPY validator_service/ validator_service/
COPY consensus_service/ consensus_service/

# CMD переопределяется в docker-compose для каждого сервиса
CMD ["uvicorn", "main_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
