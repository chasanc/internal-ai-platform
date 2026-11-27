# Build from the repo root: docker build -f services/tool-runner/Dockerfile .
FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir fastapi httpx pydantic pyyaml uvicorn
COPY services/tool-runner/runner ./services/tool-runner/runner
# the tools and registry are read at start: a missing tool or alias stops the service
COPY tools ./tools
COPY registry ./registry
COPY evals/__init__.py evals/tools.py evals/stats.py ./evals/
COPY gateway/__init__.py gateway/pii.py ./gateway/
ENV PYTHONPATH=/srv:/srv/services/tool-runner
RUN useradd --system app
USER app
EXPOSE 8000
CMD ["uvicorn", "runner.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
