FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    ca-certificates git python3 python3-pip curl nodejs npm \
    tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-jpn tesseract-ocr-kor \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /office

# Python deps — читаем из requirements.txt, не дублируем список руками.
# (Было: жёсткий список pip install, из которого исчез feedparser —
# сборщик новостей падал 'No module named feedparser' с самого начала
# и никто не заметил, потому что try/except гасил ошибку молча.)
COPY requirements.txt /office/requirements.txt
RUN pip3 install -r requirements.txt --break-system-packages

# Metalogos v0.27.0 — прод-бинарь (переход 0.25.0→0.27.0, ADR-0009;
# бинарь из официального CI-артефакта тегового коммита 0d1cce9 —
# unfreeze-релиз: В17-фиксы памяти + security-волна 0.26.0 №454-№459)
# bin/mlog-020 (0.20.0) — аварийный фолбэк guard-пробы entrypoint (lax-аудит,
# грузит сырой app.mlog). bin/mlog-025 (0.25.0) вендорен как прошлый-хороший
# тест-гвард (ADR-0009); mlog-024 выведен из репо (история git сохраняет).
COPY bin/mlog /usr/local/bin/mlog
COPY bin/mlog-020 /usr/local/bin/mlog-020
COPY bin/mlog-025 /usr/local/bin/mlog-025
RUN chmod +x /usr/local/bin/mlog /usr/local/bin/mlog-020 /usr/local/bin/mlog-025 && /usr/local/bin/mlog --version

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
RUN chmod +x /office/bin/mlog /office/bin/mlog-020 /office/bin/mlog-025 \
    && /office/bin/mlog --version

# Node.js deps (Prisma client for PostgreSQL)
RUN npm install --production 2>/dev/null || true
RUN npx prisma generate 2>/dev/null || true

RUN mkdir -p /office/data /tmp

# FO-014: office-owned MCP-серверы (github + filesystem) — исполняемые,
# вызываются из mlog через mcp_call (allowlist: mcp_servers/github,mcp_servers/filesystem)
RUN chmod +x /office/mcp_servers/github /office/mcp_servers/filesystem \
    && mkdir -p /office/data/documents /office/data/logs
RUN git config --global user.email "agent@fosved.office" \
    && git config --global user.name "Fosved Agent"

EXPOSE 10000

# #445 A.4: HEALTHCHECK — /health через reverse_proxy → mlog (программный
# роут app.mlog:1744; serve гарантирует 200 даже без объявления). Падение
# цепочки прокси+mlog роняет контейнер (совместно с супервизией #445 A.2).
# start-period=120 с: бут долгий (skills bootstrap, DB backup, mlog serve).
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -sf http://127.0.0.1:${PORT:-10000}/health || exit 1

CMD ["bash", "entrypoint.sh"]
