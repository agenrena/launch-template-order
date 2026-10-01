FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home app
COPY backend/ ./
RUN mkdir -p /app/media && chown app:app /app/media
ENV MEDIA_ROOT=/app/media
USER app
EXPOSE 8000
# Same server as local (scripts/start.py). Proxy headers pass through unchanged;
# Django trusts X-Forwarded-Proto only when TRUST_PROXY=true.
CMD ["sh", "-c", "exec waitress-serve --listen=*:${PORT:-8000} --threads=8 --no-clear-untrusted-proxy-headers config.wsgi:application"]
