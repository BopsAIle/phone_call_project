FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps ./apps
COPY shared ./shared
COPY knowledge ./knowledge
COPY prompts ./prompts
COPY specs ./specs

RUN pip install --no-cache-dir -e .

EXPOSE 8000 8001 8002
CMD ["python", "-m", "apps.voice_agent"]
