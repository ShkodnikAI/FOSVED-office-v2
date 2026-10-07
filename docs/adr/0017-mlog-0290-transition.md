# ADR-0017: Переход боевого бинаря Metalogos с 0.28.0 на 0.29.0 (релиз-гейт 0.29 GREEN, loop-семантика №608, HTTP-outcome taxonomy №592)

**Статус:** принято (прямое указание владельца «Новый релиз 0.29.0, переходим
на него», 2026-10-07; исполнение — наряд-конвейер, база main @ `6811903`).

**Контекст решения:** Metalogos v0.29.0 (тег, published 2026-10-06 14:17 UTC,
source commit `4be0f72`) — релиз, закрывающий гейт 0.29 (X-3 precise-share
3042 bp ≥ 3000 bp, OWNER-FIXED ADR-0181 §3.1; v2-gate читен GREEN в №614).
В диапазон v0.28.0..v0.29.0 входят и релизы 0.28.1/0.28.2: офис перепрыгивает
линию 0.28.x целиком, включая security-фикс Y-1 RESPOND_SWALLOWED
(release-block: голый respond* под блок-формой if/else блокирует run/serve).

## Состав релиза, значимый для офиса

- **Y-1 (0.28.2, security, release-block):** bare respond* под top-level
  блок-формой if/else снова блокирует run/serve. Офисный корпус
  (AUG-копия app.mlog) пробит на 0.29.0 — serve-бут чистый (см.
  «Верификация», п. 5), ремедиаций не потребовалось.
- **№608, loop-семантика:** голый вызов в теле цикла больше не завершает
  цикл, хвосты исполняются, «вакуумные зелёные» устранены как класс
  (harness читает ControlFlow). Поведенческое изменение — офисные dept-файлы
  проверены audit-паритетом (байт-в-байт с 0.28.0) и полным стеком serve.
- **№592, HTTP-outcome taxonomy:** per-call HTTP deadline и классификация
  HTTP_TIMEOUT / HTTP_CONNECT / HTTP_STATUS / HTTP_TIMEOUT_RANGE,
  mid-response break un-laundered. В песочнице без внешних сервисов
  офисные http_*-вызовы громко ловятся как `[HTTP_CONNECT]`/`[HTTP_STATUS]`
  внутри `[try] caught` (грейсфул — ожидаемо); в проде с ключами поведение
  то же, коды ошибок точнее.
- **№611, schema-as-code:** квалифицированное имя парсится в каждом
  спейсинге, DDL dry-run на SSOT-рендере (`ast::schema_table_ddl`).
- **№584, VM respond-terminality:** терминальный lowering на TW
  early-answer поверхности, VM-гейт снят до advisory.
- Additive: №589 UTC-календарь (now_unix, date_parse_iso, date_diff_days,
  date_format_iso), №590 normal_sample (Box-Muller), №591 Lomb–Scargle,
  №599 media-bridge (vision_understand / ocr_extract принимают
  Media(Image)), №605 X-3 precise-share в блокирующем CI-гейте.

## Вендоринг

**`bin/mlog` = 0.29.0.** Источник — релиз-артефакт `mlog-linux-x86_64`
тега `v0.29.0` (asset id 615737785, 35 118 864 байт), сверка:
`sha256 = 256bed0dd4a7ae08fe913b6da11cd20d7b52c5fd43adcd98dcb18144076a99f5`
(= SHA256SUMS релиза; сверены также BUILD-INFO.txt и CycloneDX SBOM
`mlog-linux-x86_64.cdx.json` — обе подписи OK), BUILD-INFO: source commit
`4be0f729e13d77b234cc595589049926dbd4d909`, rustc 1.99.0,
`cargo build --release --locked -p metalogos-server --bin mlog`;
`mlog --version` → `mlog mlog 0.29.0` (grammar rev: 1).
Наблюдение (апстрим): в списке ассетов v0.29.0 нет Sigstore-аттестаций,
которые ADR-0015 фиксировал для v0.28.0 — supply-chain-наблюдение
передаётся владельцу, офисную верификацию SHA256SUMS+SBOM оно не ослабляет.

**`bin/mlog-0271` (0.27.1) и `bin/mlog-020` (0.20.0) — без изменений:**
тест-гвард и аварийный фолбэк guard-пробы entrypoint (ADR-0015/0009).
Линия 0.28.x в репо не вендорится: фикс Y-1 включён в 0.29.0, сама линия
0.28.0/0.28.1 поражена Y-1 (боевым быть не может), в тестах не используется.

## Верификация (метод каждой цифры)

1. **sha256** — `sha256sum -c SHA256SUMS` → OK по всем трём файлам
   (mlog-linux-x86_64, mlog-linux-x86_64.cdx.json, BUILD-INFO.txt).
2. **Версия** — `bin/mlog --version` → `mlog mlog 0.29.0`, grammar rev: 1.
3. **Parse-критерий** — `mlog check` на app.mlog + consensus.mlog +
   24 dept-файла + dogfood_staging.mlog: **0 parse errors** на 0.29.0
   (rc≠0 у 27 файлов — warnings-only: REDACT audit-события, не ошибки
   разбора; тот же результат на 0.28.0). `library/brand.mlog` и
   `library/personas.mlog` дают parse error И на 0.29.0, И на 0.28.0 —
   не-стендэлон файлы (импортируются app.mlog), в CI не чекаются отдельно,
   поведение идентично линии.
4. **Audit-паритет** — AUG-копия app.mlog (мост №421: строка
   `profile legacy { egress: permissive_with_audit }`): rc=2, 0 `[ERROR]`,
   вывод байт-идентичен 0.28.0 (`diff` пуст). Raw app.mlog: rc=1,
   `Summary: 42 errors, 32 warnings, 267 passed`, 0 Category A (долг
   №327 без изменений) — вывод байт-идентичен 0.28.0. dept/*.mlog —
   все rc∈{0,2} на 0.29.0.
5. **Serve-бут полного стека** — `scripts/serve_stack.sh` на чистом
   `git archive HEAD` с каждым бинарем: boot `/health` ok, `/version` ok,
   webhook /status ok, /osp/analyze ok (ping + боевой graceful), /lz ok,
   /cron/control ok, /schedules/list — полный реестр 23 слотов.
   Дифф отчётов 0.28.0 vs 0.29.0 — 22 строки, все объяснимы: 2 строки
   заголовков (путь бинаря/тег) + 8 новых строк
   `[try] caught error: [HTTP_CONNECT]/[HTTP_STATUS]` (taxonomy №592
   громко классифицирует то, что раньше тонуло в общем потоке; песочница
   без внешних сервисов), + перестановка 8 строк SQL_ERROR duplicate-column
   (идемпотентные миграции, порядок ловли в try различается между
   прогонами, состав идентичен).
6. **Полный pytest** — на ветке перехода: 1266 passed, 3 failed, 2 skipped
   (дельта=0 к базлайну main @ `6811903`: идентичный набор из 3 переносимых
   фейлов — живая untracked `data/fosved.db` и среда песочницы, оба прогона
   137.0 s один в один; включает барьер прод-старта test_prod_boot на новом
   бинаре).
7. **VM-проба (evidence для FO-050, office#182)** —
   `METALOGOS_SERVE_BACKEND=vm mlog serve` на AUG-копии, свежая база:
   boot `[server] backend: vm (bytecode VM, explicit)`,
   `[db] Connected: sqlite:…` — **блокер db_decl (находка №419) исправлен
   апстримом** (Office-проба 2026-09-27 на 0.27.0: connect fail).
   Остаточный разрыв: **на VM db_decl-DDL не исполняется** — свежая база
   после бута VM содержит 0 таблиц (interpreter на том же корпусе и env:
   134 таблицы), `/health` → `no such table: admin_proposals`; одинаково
   на 0.28.0 и 0.29.0 (диагноз апстримный, не регрессия перехода).
   Для стейджинга с уже существующей схемой это может быть не-блокером —
   решение о VM-флипе за владельцем (office#182, вариант А).

## Следствия

1. CI-гвард №312 (audit dept) по-прежнему rides `bin/mlog-0271`;
   parse-гейты — `bin/mlog` (0.29.0).
2. Гвард версий обновлён: test_n399_a2_llm_757 A.2.1 — 0.29.0 + sha256
   артефакта (`256bed0d…`).
3. Деплой владельцем на Render подхватит 0.29.0 автоматически (образ
   собирается из этого Dockerfile); ожидание бут-лога: guard-проба rc=2
   (warnings only), «native schedules OK», /version OK. Новое в прод-логах:
   строки taxonomy №592 при сетевых сбоях — норма, не инцидент.
4. FO-050 (office#182): вариант А (VM-флип стейджинга) — блокер №419 снят,
   актуальный статус «DDL-bootstrap на VM отсутствует (0 таблиц vs 134)»;
   sprint-итог soak и рекомендации — в office#182.
