# RunSense: one container serving the web app and the API (/api).
# Built and run by Zeabur; works the same with plain `docker build`.

# ---- web app ----
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# the API is reached on the same origin under /api (see backend/app/serve.py)
ENV VITE_API_BASE_URL=/api
RUN npm run build

# ---- API + static server ----
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RUNSENSE_WEB_DIST=/srv/web/dist \
    PORT=8080
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/constraints.txt ./
COPY backend/app ./app
COPY backend/ml ./ml
RUN pip install -c constraints.txt . tzdata
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/scripts ./scripts
COPY --from=web /web/dist /srv/web/dist
EXPOSE 8080
# bring the schema up to date, then serve
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.serve:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
