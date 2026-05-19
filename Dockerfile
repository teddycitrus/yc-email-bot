# Container image for serverless / managed Python hosts (Hugging Face Spaces,
# Render, Fly, Railway, etc.). The host injects $PORT; we fall back to 7860
# which is Hugging Face Spaces' default.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EMAIL_ME_DEFAULT_NO_SMTP=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY email_me ./email_me

RUN pip install --upgrade pip && pip install ".[web]" gunicorn

# --timeout 600 keeps long streaming responses alive; gthread workers handle
# concurrent slow streams without blocking. Bind to 0.0.0.0 for the host.
CMD ["sh", "-c", "exec gunicorn --workers 2 --threads 4 --worker-class gthread --timeout 600 --bind 0.0.0.0:${PORT:-7860} 'email_me.web:create_app()'"]
