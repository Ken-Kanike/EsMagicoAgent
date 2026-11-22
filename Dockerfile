# Container image for hosting the API + dashboard (Render, Hugging Face Spaces, Koyeb, Railway, any VM).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OpenCV (pulled in by rapidocr-onnxruntime) needs these shared libraries on slim images.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a non-root user (uid 1000 also matches Hugging Face Spaces); the app writes
# uploads, dashboard results, templates and the result cache inside /app.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p temp_upload outputs/dashboard templates .cache \
 && chown -R app:app /app
USER app

# Render/Koyeb/Railway inject PORT; Hugging Face Spaces expects 7860 (set PORT=7860 there).
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
