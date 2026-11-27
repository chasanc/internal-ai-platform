# Build from the repo root: docker build -f templates/python-service/Dockerfile .
FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastapi httpx pydantic uvicorn
COPY templates/python-service/app ./app
RUN useradd --system app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
