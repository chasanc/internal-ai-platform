# Build from the repo root: docker build -f services/support-triage/Dockerfile .
FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastapi httpx pydantic uvicorn "psycopg[binary]"
COPY services/support-triage/app ./app
COPY services/support-triage/prompts ./prompts
# shared strict output contract, also used by the evals
COPY evals/__init__.py evals/schema.py ./evals/
# PII masker, applied before any text leaves for the gateway
COPY gateway/__init__.py gateway/pii.py ./gateway/
RUN useradd --system app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
