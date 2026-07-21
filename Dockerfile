FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.lock ./
RUN python -m pip install --upgrade pip==26.1.2 \
    && python -m pip install --require-hashes -r requirements.lock

COPY search_agent_lab ./search_agent_lab
COPY spooky ./spooky

RUN useradd --create-home --uid 10001 spooky
USER spooky

EXPOSE 8080
CMD exec python -m uvicorn search_agent_lab.spooky_api:app \
    --host 0.0.0.0 \
    --port "${PORT:-8080}"
