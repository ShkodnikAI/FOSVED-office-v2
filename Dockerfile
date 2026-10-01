FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    ca-certificates git python3 python3-pip curl nodejs npm \
    tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-jpn tesseract-ocr-kor \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /office

# Python deps — сборка по LOCK-файлу (#450 A.2): версии закреплены pip-compile,
# сборка воспроизводима. Обновление зависимостей — отдельный PR:
#   pip-compile --output-file=requirements.lock requirements.txt
# (локально: python3 -m piptools compile; diff ревьюится, апгрейды — осознанно).
COPY requirements.txt /office/requirements.txt
COPY requirements.lock /office/requirements.lock
RUN pip3 install -r requirements.lock --break-system-packages

# Metalogos v0.27.0 — прод-бинарь (переход 0.25.0→0.27.0, ADR-0009;
# бинарь из официального CI-артефакта тегового коммита 0d1cce9 —
# unfreeze-релиз: В17-фиксы памяти + security-волна 0.26.0 №454-№459)
# bin/mlog-020 (0.20.0) — аварийный фолбэк guard-пробы entrypoint (lax-аудит,
# грузит сырой app.mlog). bin/mlog-027 (0.27.0) вендорен как прошлый-хороший
# тест-гвард (ADR-0012; было mlog-025 — выведен #399, а COPY здесь забыли →
# сборка падала 30.09–01.10, хотфикс 2026-10-01).
COPY bin/mlog /usr/local/bin/mlog
COPY bin/mlog-020 /usr/local/bin/mlog-020
COPY bin/mlog-027 /usr/local/bin/mlog-027
RUN chmod +x /usr/local/bin/mlog /usr/local/bin/mlog-020 /usr/local/bin/mlog-027 && /usr/local/bin/mlog --version

COPY entrypoint.sh /office/entrypoint.sh
RUN chmod +x /office/entrypoint.sh
COPY . .

# №419 follow-up / №349: вендоренные бинари приходят через COPY . . —
# exec-бит должен жить в самом git (100755); chmod ниже — страховка, чтобы
# аудиторская проба entrypoint ("-x $MLOG_CANDIDATE") физически запускалась
# в образе. Без него guard-переход молча вечно едет на фолбэк и
# нативный cron никогда не бутстрапится (предусловие А cutover-чеклиста).
# Инцидент 2026-09-25: наряд №372 заменил бинарь через GitHub API — моды в git
# стали 100644, а эта строка по-прежнему chmod'ила УДАЛЁННЫЙ mlog-023 →
# docker build падал, деплой не проходил. Страховка теперь гоняет ВСЕ
# вендоренные бинари (защита от регресса exec-бит) и верифицирует кандидата.
RUN chmod +x /office/bin/mlog /office/bin/mlog-020 /office/bin/mlog-027 \
    && /office/bin/mlog --version

# Node.js deps (Prisma client for PostgreSQL)
RUN npm install --production 2>/dev/null || true
RUN npx prisma generate 2>/dev/null || true

RUN mkdir -p /office/data /tmp

# ── #450 A.1: непривилегированный пользователь ──────────────────────────────
# Процессы офиса (Flask/waitress, mlog, прокси, tg-monitor) не от root.
# Постоянные диски Render: /var/data (DATABASE_PATH), /var/forge (FORGE exec
# и бэкапы) — владелец office; /office целиком (data/, visuals/, forge-tmp,
# VERSION, memories) тоже офису. Порты >1024 — root не нужен.
RUN useradd -r -u 10001 -m -d /home/office office \
    && mkdir -p /var/data /var/forge/repos \
    && chown -R office:office /office /var/data /var/forge

# ХОТФИКС 2026-10-01: USER office ВРЕМЕННО СНЯТ. Постоянный диск Render
# монтируется поверх /var/data при запуске — chown выше действует только на
# слой образа; база на диске создана процессами от root → под office запись
# в базу не гарантирована. Вернуть USER только вместе со сбросом привилегий в
# entrypoint (chown диска от root, затем setpriv/gosu → office) — наряд #450.
# USER office
# git-идентичность FORGE — системная, работает под любым пользователем
RUN git config --system user.email "agent@fosved.office" \
    && git config --system user.name "Fosved Agent"

# FO-014: office-owned MCP-серверы (github + filesystem) — исполняемые,
# вызываются из mlog через mcp_call (allowlist: mcp_servers/github,mcp_servers/filesystem)
RUN chmod +x /office/mcp_servers/github /office/mcp_servers/filesystem \
    && mkdir -p /office/data/documents /office/data/logs

EXPOSE 10000

# #445 A.4: HEALTHCHECK — /health через reverse_proxy → mlog (программный
# роут app.mlog:1744; serve гарантирует 200 даже без объявления). Падение
# цепочки прокси+mlog роняет контейнер (совместно с супервизией #445 A.2).
# start-period=120 с: бут долгий (skills bootstrap, DB backup, mlog serve).
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -sf http://127.0.0.1:${PORT:-10000}/health || exit 1

CMD ["bash", "entrypoint.sh"]
