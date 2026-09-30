# Деплой test_hub на сервер

Это пошаговый плейбук для переноса test_hub с macOS владельца (запуск под
`launchd`, см. README «Установка и запуск») на Linux-сервер. Локальный запуск
для разработки — см. README, здесь только сценарии сервера.

Два независимых варианта установки — Docker (раздел 1) и без Docker, через
systemd (раздел 2). Дальше (перенос данных, подключение тестовых проектов,
обновление, откат, логи) — общие шаги с пометками, где Docker- и
systemd-вариант отличаются.

## 1. Сервер с нуля — вариант Docker

Понадобится Docker и Docker Compose на сервере, ssh-доступ, клон репозитория
test_hub (`git clone <repo> /opt/test_hub && cd /opt/test_hub`).

1. Создайте `.env` из примера и заполните значения для прод-режима:
   ```bash
   cp .env.example .env
   ```
   Обязательно замените:
   - `TH_SECRET` — случайная строка (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).
   - `TH_PUBLIC_URL` — внешний адрес (например `https://qa.example.com`, если
     дальше стоит nginx с HTTPS, см. раздел 2 — nginx одинаково нужен и с
     Docker, и без).
   - `TH_ENV=prod` — включает проверку `TH_SECRET` и случайные seed-пароли
     (подробности — в разделе «Безопасность прод-режима» ниже).

   Для подключения тестовых проектов внутри контейнера пропишите в `.env`:
   ```
   TH_PROJECTS_ROOT=/projects
   TH_VSHGU_PATH=/projects/auto_tests_vshgu
   ```
   (см. раздел 4 — это те же переменные, что читает `app/config.py`).

2. Смонтируйте репозитории тестовых проектов в `docker-compose.yml` — там уже
   есть закомментированный пример строки под `auto_tests_vshgu`, раскомментируйте
   и укажите свой путь на хосте, добавьте по такому же образцу для остальных
   проектов:
   ```yaml
   volumes:
     - ./workspace:/app/workspace
     - ./.env:/app/.env:ro
     - /path/to/auto_tests_vshgu:/projects/auto_tests_vshgu
   ```

3. Соберите и поднимите:
   ```bash
   docker compose up -d --build
   ```
   test_hub слушает `0.0.0.0:${TH_PORT:-8700}` внутри контейнера (см.
   `Dockerfile`), наружу пробрасывается тот же порт. `./workspace` на хосте —
   постоянные данные (БД и всё остальное, см. раздел 3).

4. Образ сам не создаёт venv тестовых проектов — только один раз после
   монтирования репозитория (см. раздел 4).

## 2. Сервер с нуля — вариант без Docker (systemd)

Целевая ОС — Ubuntu. Клонируйте репозиторий туда, где он должен остаться жить
(`deploy/install.sh` настраивает systemd на этот же каталог, отдельного
переноса в `/opt` после клонирования скрипт не делает):

```bash
git clone <repo> /opt/test_hub && cd /opt/test_hub
sudo TH_SERVICE_USER=test_hub deploy/install.sh
```

Скрипт идемпотентен (безопасно перезапускать) и делает всё за один проход:
ставит `python3.11`/`python3.11-venv`, JRE для Allure, `curl`/`rsync`/`sqlite3`;
скачивает и распаковывает Allure CLI (версия `2.32.0` по умолчанию,
`TH_ALLURE_VERSION` — переопределить) и линкует его в `/usr/local/bin/allure`;
заводит системного пользователя `test_hub` (или значение `TH_SERVICE_USER`) без
шелла и отдаёт ему каталог приложения; создаёт `.venv`, ставит
`requirements.txt` и `playwright install-deps` (системные библиотеки для
headless Chromium — общие для всех venv тестовых проектов на сервере, поэтому
ставятся один раз здесь, не в каждом venv отдельно); создаёт `.env` из
`.env.example`, если его ещё нет; устанавливает `deploy/test_hub.service` в
`/etc/systemd/system/test_hub.service` (подставив реальный путь и
пользователя вместо плейсхолдеров `/opt/test_hub`/`test_hub`) и включает +
запускает сервис.

После первого запуска отредактируйте `${APP_DIR}/.env` (как минимум
`TH_SECRET`, `TH_PUBLIC_URL`, `TH_ENV=prod`, при необходимости
`TH_PROJECTS_ROOT`/`TH_VSHGU_PATH`, см. раздел 4) и перезапустите:

```bash
sudo systemctl restart test_hub
```

Под systemd `PATH` урезан — если Allure не находится автоматически, пропишите
`TH_ALLURE_BIN=/usr/local/bin/allure` в `.env` (то же самое, что описано в
README «Allure CLI» для `launchd`).

### nginx как reverse proxy (нужен в обоих вариантах — Docker и systemd)

test_hub слушает только `127.0.0.1:<TH_PORT>`, снаружи — nginx с HTTPS.
Пример готов в `deploy/nginx.conf.example`:

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/test_hub
# заменить example.com и пути сертификатов на реальные
sudo ln -s /etc/nginx/sites-available/test_hub /etc/nginx/sites-enabled/test_hub
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d example.com
```

В примере два важных момента: отдельный `location /ws/runs/` с
`proxy_set_header Upgrade`/`Connection "upgrade"` и увеличенным
`proxy_read_timeout 3600s` — это WebSocket живого лога прогона
(`app/routers/runs.py`, `@ws_router.websocket`), без апгрейда соединения лента
прогона в браузере не заработает; и `client_max_body_size 20m` — под кадры
UI-тестов и вложения к тест-кейсам (`TH_FRAME_MAX_BYTES`,
`TH_TESTCASE_ATTACHMENT_MAX_BYTES` в `app/config.py`).

## 3. Перенос workspace/ с мака владельца на сервер

`workspace/` — единственный каталог с состоянием test_hub, целиком переносимый:
БД (`test_hub.db`), результаты и HTML-отчёты Allure (`allure-results/`,
`allure-reports/`), кадры UI-тестов (`frames/`), скриншоты тест-кейсов
(`testcases/`), кэш карты покрытия (`coverage/`) и производные разделы/
статистика/карта продукта — все они подкаталоги одного `WORKSPACE_DIR`
(`app/config.py`).

Перенос — `deploy/migrate_workspace.sh`, запускать **с мака владельца**, где
сейчас лежат данные:

```bash
deploy/migrate_workspace.sh user@server:/opt/test_hub
# или явно указать источник, если он не рядом со скриптом:
TH_MIGRATE_SRC=/Users/andreykorotkow/.../test_hub/workspace \
  deploy/migrate_workspace.sh user@server:/opt/test_hub
```

Скрипт сам: останавливает `test_hub` на сервере по ssh (`sudo systemctl stop
test_hub`), чтобы БД не менялась во время копирования; синхронизирует
`workspace/` через `rsync -az --delete`; проверяет целостность перенесённой БД
(`sqlite3 ... 'PRAGMA integrity_check;'`) и запускает сервис обратно; если
результат проверки не `ok`, скрипт завершается с ошибкой и просит проверить
БД вручную, не доверяя данным молча.

Важно: скрипт останавливает/запускает сервис командой `systemctl` — это
рассчитано на systemd-вариант установки (раздел 2). Для Docker-варианта перед
запуском скрипта остановите контейнер вручную (`docker compose stop`) и
запустите обратно после проверки целостности (`docker compose up -d`) — сам
скрипт при неудачной `systemctl stop` только печатает предупреждение и
продолжает, не блокируя rsync.

## 4. Подключение проектов тестов на сервере

test_hub сам не клонирует репозитории тестов и не создаёт их окружение — это
ручной шаг, тем же способом, каким владелец уже делает это на маке. Разница
между Docker- и systemd-вариантом — только путь, где тестовые проекты лежат.

1. **Клонируйте репозиторий тестового проекта** на сервер:
   - Docker: в точку монтирования из `docker-compose.yml`, например
     `/path/to/auto_tests_vshgu` на хосте (смонтирована в контейнер как
     `/projects/auto_tests_vshgu`, см. раздел 1);
   - systemd: в любой каталог на сервере, путь к которому пропишете в
     `TH_PROJECTS_ROOT`/`TH_VSHGU_PATH` в `.env` test_hub (`app/config.py`).

2. **`.env` самого тестового проекта** (базовые URL стендов, секреты для его
   собственных тестов и т.п.) настраивается по README этого проекта — test_hub
   от него не зависит и в него не заглядывает.

3. **venv тестового проекта создаётся один раз вручную**, тем же способом, что
   и на маке владельца:
   ```bash
   cd /projects/auto_tests_vshgu   # или systemd-путь из TH_VSHGU_PATH
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/playwright install --with-deps chromium   # если в проекте есть UI-тесты
   ```
   Для Docker — та же команда, но внутри контейнера:
   ```bash
   docker compose exec test_hub bash -lc \
     "cd /projects/auto_tests_vshgu && python3 -m venv .venv \
      && .venv/bin/pip install -r requirements.txt \
      && .venv/bin/playwright install --with-deps chromium"
   ```
   Это осознанный выбор, а не упущение: раннер (`app/core/runner.py`) ищет
   `<путь_проекта>/<venv>/bin/python` и просто отдаёт понятную ошибку, если
   его нет, вместо того чтобы создавать venv лениво по требованию — иначе
   пришлось бы решать в раннере, когда venv «устарел» и нужно пересоздать
   (изменился `requirements.txt`, сменилась версия python), ради события,
   которое происходит редко (новый проект или смена его зависимостей), а не
   при каждом прогоне.

4. **Регистрация проекта в test_hub** зависит от того, что это за проект:
   - **`auto_tests_vshgu`** — особый случай: `app/db.py::_seed_vshgu_project`
     проверяет `TH_VSHGU_PATH` на каждом старте test_hub (не только на пустой
     БД) и сам создаёт проект `VSHGU` со стендами `develop`/`stage` (плюс
     пресеты запуска для `stage`), если их ещё нет. Значит после клонирования
     репозитория и настройки `TH_VSHGU_PATH` достаточно перезапустить test_hub
     (`systemctl restart test_hub` / `docker compose restart test_hub`) — сам
     проект появится без ручных действий в UI.
   - **Остальные проекты** (`bike_fit`, `Velo_bot` и любые новые) сидируются
     из `SEED_PROJECTS` в `app/db.py` только на **пустой** БД (первый старт
     test_hub без данных). На уже работающем сервере с непустой БД (обычный
     случай — сервер уже отработал какое-то время, или после переноса
     workspace/ из раздела 3) добавить новый проект тестов нужно вручную через
     раздел администрирования в UI (создание проекта: имя, путь, `venv`,
     стенды) — так же, как это делает qa/admin на маке владельца сейчас.

## 5. Обновление

**Docker:**
```bash
cd /opt/test_hub
git pull --ff-only
docker compose up -d --build
```
(пересобирает образ при изменении `Dockerfile`/`requirements.txt`,
перезапускает контейнер; `./workspace` не трогается — том, не часть образа).

**systemd:**
```bash
sudo deploy/update.sh
```
Скрипт делает `git pull --ff-only` от имени сервисного пользователя,
`pip install -r requirements.txt` в существующий `.venv` и
`systemctl restart test_hub` (то же самое можно руками:
`cd /opt/test_hub && git pull && sudo systemctl restart test_hub`, как
написано в комментарии `deploy/test_hub.service`).

## 6. Откат

Откат кода — обычный git, затем перезапуск тем же способом, что и обновление:

```bash
cd /opt/test_hub
git log --oneline -10        # найти коммит/тег, на который откатываемся
git checkout <commit-or-tag>
# Docker:
docker compose up -d --build
# systemd:
sudo -u test_hub .venv/bin/pip install -r requirements.txt -q
sudo systemctl restart test_hub
```

Если откат кода расходится по схеме БД с текущими данными (редкий случай —
миграции в `app/db.py` только добавляют колонки/таблицы, откат назад обычно
безопасен), восстановите БД из бэкапа `deploy/backup.sh`:

```bash
sudo systemctl stop test_hub   # или docker compose stop
cp workspace/backups/test_hub_<TIMESTAMP>.db workspace/test_hub.db
sudo systemctl start test_hub  # или docker compose up -d
```

`deploy/backup.sh` кладёт снимки БД в `workspace/backups/test_hub_<таймстамп>.db`
через онлайн-бэкап `sqlite3 ... .backup` (безопасен без остановки сервиса) и
сразу проверяет их целостность (`PRAGMA integrity_check`). Запуск вручную —
`deploy/backup.sh`; для регулярного бэкапа — пример строки в crontab уже есть
в комментарии самого скрипта (ежедневно в 03:15, хранит последние 14 бэкапов
по умолчанию, `TH_BACKUP_KEEP` — переопределить).

## 7. Где смотреть логи

**systemd:**
```bash
journalctl -u test_hub -f          # непрерывно
journalctl -u test_hub --since "1 hour ago"
```
(`deploy/test_hub.service` не перенаправляет stdout/stderr отдельно — всё идёт
в journald, включая предупреждения о ненайденном Allure и сгенерированных
seed-паролях, см. ниже).

**Docker:**
```bash
docker compose logs -f test_hub
```

## Безопасность прод-режима

`TH_ENV` переключает три вещи (по умолчанию `dev` — поведение не отличается от
текущей установки на маке владельца):

- **`TH_SECRET`.** При `TH_ENV=prod` и незаменённом `TH_SECRET=change-me`
  (значение из `.env.example`) сервер отказывается стартовать —
  `app/main.py::_check_prod_secret` поднимает исключение в `lifespan` ещё до
  `init_db()`, uvicorn не поднимется вообще, с сообщением, что нужно задать
  случайный `TH_SECRET` (команда генерации — в самом тексте ошибки). В `dev`
  дефолт остаётся рабочим (локально/под `launchd`, как сейчас).
- **`TH_PUBLIC_URL`.** Используется только для ссылок «Поделиться» на отчёты
  (`app/routers/share.py`) и в сообщениях Telegram-бота — не влияет на то, на
  каком адресе слушает сам процесс (`TH_PORT`/`0.0.0.0` в Docker). В проде
  обязательно должен указывать на реальный внешний адрес (за nginx), иначе
  сгенерированные ссылки будут вести на `127.0.0.1`.
- **Seed-пароли.** При `TH_ENV=prod` `app/db.py` не создаёт пользователей с
  паролями по умолчанию — ни для `qa`/`manager`/`customer` (`_seed_if_empty`),
  ни для `admin` (`_seed_superadmin`): для каждого из них генерируется
  случайный пароль (`secrets.token_urlsafe(12)`) и одноразово выводится в лог
  процесса (`_log_generated_passwords` — предупреждение уровня `WARNING`,
  видно через `journalctl -u test_hub` или `docker compose logs`); повторно
  открытым текстом он нигде не хранится и не печатается, в БД попадает только
  его хэш (`hash_password`). Принудительной смены пароля при первом входе в UI
  нет — это сознательное упрощение вместо новой колонки/экрана. Это
  выполняется на каждой из четырёх сидируемых учёток, а не только на `qa` и
  `admin`, как можно было бы предположить по умолчаниям `dev`-режима
  (`qa/qa`, `manager/manager`, `customer/customer`, `admin/admin`).
  Учётка `tg_bot` (сервисный логин бота, `_seed_tg_bot_user`) в этой логике
  не участвует и создаётся с паролем из `TH_TG_SERVICE_PASSWORD` независимо от
  `TH_ENV` — при развёртывании в проде задайте её через `.env`, а не полагайтесь
  на дефолт `tg_bot`/`tg_bot`.

См. также README «Установка и запуск» (локальный запуск, переменные
`.env.example`) и «Allure CLI» (поиск бинарника `allure`, актуально и на
сервере под systemd/Docker — та же логика `TH_ALLURE_BIN`, что и под
`launchd`).
