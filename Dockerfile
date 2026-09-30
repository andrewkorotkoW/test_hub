# test_hub в Docker: см. docs/missions/2026-09-30_server_readiness.md (пункт 2) и
# docs/DEPLOY.md — там описано, как подключать репозитории тестовых проектов и
# создавать их venv внутри контейнера (этот образ сам их не создаёт).
FROM python:3.11-slim

# Java (headless JRE) нужна только Allure CLI (java -jar внутри его bin/allure);
# curl/ca-certificates — скачать сам Allure; git — раннер клонирует/обновляет
# репозитории тестовых проектов не сам, но тестовые проекты внутри /projects
# нередко используют git (например для версии в отчёте).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-jre-headless \
        curl \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Allure CLI — версия зафиксирована (та же, что в примере README/TH_ALLURE_BIN),
# ставится из tar.gz с GitHub Releases, не из apt (в Debian его нет).
ARG ALLURE_VERSION=2.32.0
RUN curl -fsSL -o /tmp/allure.tgz \
        "https://github.com/allure-framework/allure2/releases/download/${ALLURE_VERSION}/allure-${ALLURE_VERSION}.tgz" \
    && tar -xzf /tmp/allure.tgz -C /opt \
    && rm /tmp/allure.tgz
ENV TH_ALLURE_BIN=/opt/allure-${ALLURE_VERSION}/bin/allure

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Headless Chromium + его системные библиотеки (libnss3, libatk и т.п.).
# test_hub сам Playwright не запускает, но раннер (app/core/runner.py) исполняет
# pytest внутри venv тестовых проектов (VSHGU и т.п.), которые тянут
# pytest-playwright для UI-тестов; для проекта Demo раннер использует venv=""
# (см. app/core/runner.py::_venv_python) — интерпретатор самого test_hub, тот же,
# что и здесь, поэтому браузер ставится прямо в системный python этого образа.
RUN playwright install --with-deps chromium

COPY . .

ENV TH_PORT=8700
EXPOSE ${TH_PORT}

# host 0.0.0.0 обязателен — app/main.py::__main__ по умолчанию слушает 127.0.0.1
# (это ветка "запустить локально на маке напрямую"), в контейнере так недоступно
# извне; порт и остальные настройки идут из .env (см. docker-compose.yml).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${TH_PORT:-8700}"]
