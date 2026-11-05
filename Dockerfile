FROM ubuntu:24.04

RUN apt-get update && apt-get install -y \
    ca-certificates git python3 python3-pip curl nodejs npm gosu \
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

# Metalogos v0.38.3 — прод-бинарь (линия
# 0.25.0→0.27.0→0.27.1→0.28.0→0.29.0→0.30.0→0.33.1→0.33.2→0.34.0→0.34.1→0.38.0→0.38.1→0.38.3, ADR-0009/0012/0015/0017/0018/0189/0197/0203;
# бинарь из официального релиза тега v0.38.3 (assets + SHA256SUMS), source commit 54f8c04,
# sha256 артефакта 4e07d11dd1881f903f519ced3abe7a6f48fb92c67a42ff0f81ce1e72057741b5 —
# внеплановый patch-релиз (наряд FOSVED-office-v2#663; решение владельца 03.11 «офис тоже
# перейдёт», выпуск 05.11): 0.38.3: №915 — serve/mcp-гейты учитывают allow(unchecked_result)
# в импортируемых модулях (№897 достроен до треугольника check↔run↔serve; офис несёт
# санкционированные allow-комментарии в импортируемых модулях); №898 (BREAKING, Metalogos-#1792) —
# откат №879: call_llm без объявленного провайдера снова громко отказывает, заглушка только по
# явному флагу — в проде провайдеры объявлены (llm{} app.mlog), прод не затронут; батарея v3 без
# llm{} идёт в ветку сбоя ревью, которая после C.1 #649 тоже паркует владельцу (awaiting_owner).
# Предыдущий пин 0.38.1 (внеплановый patch, наряд FOSVED-office-v2#649, приказ 2026-11-03,
# source 4f79b31, sha256 — SHA256SUMS тега v0.38.1): тики cron видят allow_carrier (Metalogos-#1735) — на 0.38.0
# каждый тик встроенного cron отказывал IRREVERSIBLE_NO_GRANT на валидной декларации (ночной
# цикл, утренний бриф, ответ Админа, слоты ЛЗ молча умерли 03.11); фикс возвращает permit-roster
# в нативный тик (fresh_program_context) и serve-интерпретатор (merge_interpreter). Предыдущий пин:
# 0.36.0 (ADR-0203 §2.4) — правило capability: 12 carriers PROFILE_PERMIT_SHARP (exec, exec_argv,
# delete_file, git_push, http_post, http_post_multipart, send_message, send_photo, send_document,
# smtp_send, smtp_send_html, tts_send) отказывают до запуска без profile capability { allow_carrier: "…" }
# или гранта builtin:<name>; profile legacy НЕ обходит — минимальная миграция: декларации в шапках
# точек входа (app.mlog, dogfood_staging.mlog, CI-тесты v3) — ровно три носителя офиса
# (http_post, send_message, exec; сужение до грантов builtin:* — отдельное решение владельца);
# 0.38.0 — approval-гейт cron_run (HUMAN_OVERSIGHT: IRREVERSIBLE_NO_GRANT без живого мандата
# approval_issue) — в офисе вызовов cron_run нет (grep-инвентаризация #620); 0.35.0 — паспорт
# моделей / LICENSED_FLOOR — локальных весов офис не использует (LLM через внешние API).
# Пин 0.34.1 (fdac4152, source 0f0f1293, внеплановый fix-релиз №833, приказ 2026-10-30) — история:
# №829 — фикс мис-диспетчеризации VM при profile legacy (Metalogos-#1616/#1618: чужой паттерн
# / потеря аргументов вызовов, молчаливый режим коррупции); №831 — SQL_DYNAMIC-гейт 5/5
# по классификации (query/query_row/query_scalar/db_execute арг-0, db_execute_with_grant арг-1)
# + гвард идентификаторов db_insert (fail-closed: нелитеральный SQL — громкий отказ на check;
# офисные 58 db_execute_with_grant и 8 db_insert литеральны — check обоих входов 0 новых
# находок, известные семейства на месте: [PII_EGRESS_OUTPUT] GET /schedules/list — запрет
# чинить; [BUILTIN_EXPERIMENTAL] db_insert; [SECRET_EGRESS_NETWORK] №781 — audit-события);
# 0 parse errors app/dept; grammar rev 1 — без смены ревизии грамматики.
# №829 exit (п.6 №833): CI-батарея v3 ВОЗВРАЩЕНА на боевой VM-лэйн — --reference снят
# (был: переходный TW-оракул ADR-0197, окна 0.34.0–0.34.1); 19/19 на VM. n550v3 получил
# NightSlot-стаб (класс #604 — символ app-слоя; пробел вскрылся возвратом на VM, канонка
# test_n588_night). №802: run-гейт enforce'ит sink-clearance — profile legacy в
# test_n550v3/test_n588_night ОСТАЁТСЯ (это не обходной путь, а канонка); стаб call_python
# в forge1-9v3 ОСТАЁТСЯ (№799/№800 — undefined refusal на компиляции).
# bin/mlog-0271 (0.27.1) вендорен как прошлый-хороший
# тест-гвард (ADR-0015; было mlog-027 = 0.27.0 — выведен; было mlog-025 —
# выведен #399, а COPY здесь забыли → сборка падала 30.09–01.10, хотфикс
# 2026-10-01). Аварийный фолбэк 0.20 удалён 03.11 (решение владельца, #645):
# провал guard-пробы entrypoint — громкий отказ бута, без отката на legacy.
COPY bin/mlog /usr/local/bin/mlog
COPY bin/mlog-0271 /usr/local/bin/mlog-0271
RUN chmod +x /usr/local/bin/mlog /usr/local/bin/mlog-0271 && /usr/local/bin/mlog --version

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
RUN chmod +x /office/bin/mlog /office/bin/mlog-0271 \
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

# ХОТФИКС 2026-10-01: USER office снят — сборка падала с 30.09, а постоянный
# диск Render монтируется поверх /var/data при запуске: chown выше действует
# только на слой образа; база на диске создана процессами от root.
# ВОЗВРАТ non-root (#450, замечание 1 аудита #451) — через сброс привилегий
# в entrypoint: контейнер стартует от root, entrypoint делает chown
# персистентных путей (DATABASE_PATH=/var/data, /var/forge), затем
# exec gosu office — ВСЕ процессы офиса работают от office (uid 10001).
# USER office НЕ возвращаем: бут-логика (bootstrap, seed, backup, chown)
# требует root только до первой строки сброса.
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
