# ADR-0015: Переход боевого бинаря Metalogos с 0.27.1 на 0.28.0 (семантический гейт №523, respond_html №565, честный read_file №563)

**Статус:** принято (прямое указание владельца «Вышел релиз 0.28.0, переходим на него», 2026-10-04).

**Контекст решения:** Metalogos v0.28.0 (тег, published 2026-10-03, source
commit `3576887`) — security-релиз, собранный по консолидированному аудиту
30.09 и 02.10. Релиз-нотс фиксирует: «v0.27.1 and earlier are affected —
update is mandatory». Три изменения требуют офисной адаптации, остальные —
прозрачны.

## Состав релиза, значимый для офиса

- **№523 (gh#832, N-1, High):** семантические находки теперь БЛОКИРУЮТ
  `mlog run` и `mlog serve` — `mlog serve` на 0.27.x вообще не гонял
  семантический проход; неизвестная функция возвращала строку-значение
  (truthy) — security-check становился собственным обходом. Теперь:
  refusal по коду, `[UNDEFINED_FUNCTION]` — компиляционная ошибка,
  исключения классифицируются ТОЛЬКО по структурированному виду ошибки.
  Env-обхода нет — легальная адаптация только чинить корпус.
- **№565 (gh#927 → закрытие Metalogos-#966):** 1-арг форма
  `respond_html(html)` восстановлена как SSOT (статус по умолчанию «200»),
  2-арг `respond_html(a, b)` — deprecated (warn-only), явные формы
  `respond_html_status` / `respond_html_doc`. Регрессия 0.27.x, ронявшая
  прод-страницы `/repos/*` офиса, закрыта тем же релизом (office-issue
  Р7/апстрим #966 — Resolution: вариант A реализован).
- **№563:** контракт №254 («мягкое чтение») завершён — `read_file`
  отсутствующего файла бросает громкий `[IO_ERROR]`; явный фолбэк —
  `read_file_or(path, default)` (билтин с 0.27.1, реестр 2-арг).
- Supply-chain: релизы теперь несут артефакты (mlog-linux-x86_64,
  SHA256SUMS, BUILD-INFO.txt, CycloneDX SBOM, Sigstore-аттестации);
  до v0.27.1 включительно артефактов не было.

## Вендоринг

**`bin/mlog` = 0.28.0.** Источник — релиз-артефакт `mlog-linux-x86_64`
тега `v0.28.0` (asset id 608072608), сверка:
`sha256 = 58eb1ebd0d326f071cf923acba869c4fec6c732b9458b676f158a4d743ec2260`
(= SHA256SUMS), BUILD-INFO: source commit `3576887d…`, rustc 1.99.0,
`cargo build --release --locked --bin mlog`; `mlog --version` →
`mlog mlog 0.28.0` (grammar rev: 1). Размер 34 241 776 байт.

**`bin/mlog-0271` = 0.27.1** (прошлый-хороший, тест-гвард) — тот самый
бинарь, что был боевым (sha256 `43fb5c7a…`, зафиксирован в ADR-0012).
**`bin/mlog-027` (0.27.0) выведен** из репо (история git сохраняет; линия
0.27.0 поражена обоими security-дефектами релиза — смысла в гварде нет).
`bin/mlog-020` (0.20.0) — аварийный фолбэк guard-пробы, без изменений;
фолбэк-патч #399 A.2 (sed-вырезание max_tokens/llm_last_finish_reason)
сохранён — 0.20 фичу #757 не знает, боевая линия 0.27.1+ знает.

## A. Ремедиация №523: 9 сайтов арности (блокировали бут serve)

Проба на 0.27.1 (скрипт `probe_resolve`, interpreter-бэкенд) установила:
таблица паттернов ГЛОБАЛЬНАЯ, побеждает ПЕРВОЕ определение; вызов с иной
арностью — рантайм-ошибка хендлера. Значит все 9 находок гейта — ЛАТЕНТНЫЕ
ПРОД-БАГИ 0.27.x (рул роуты в рантайме), которые гейт №523 вскрыл,
подняв до бут-блока. Список и фикс:

| # | Сайт | Дефект | Фикс |
|---|------|--------|------|
| 1 | app.mlog (бывш. 4225) | `AuditLog("lz_osint","system","lz",username,"ok")` — 5 арг при 3-парам utils | слоты выправлены: `AuditLog("lz_osint","lz","user="+username+" result=ok")` |
| 2 | dept/admin.mlog (бывш. 180) | `index_of(trimmed,"]",sev_start)` — 3 арг при 2-арг билтине | позиция `]` от sev_start: 2-арг поиск по хвосту `substring` + абсолютная поправка |
| 3 | dept/finance.mlog (бывш. 520) | `format_date("%Y-%m-%d")` — 1 арг при 2-арг | `format_date("%Y-%m-%d", now())` (семантика пробы: «2026-10-04») |
| 4-7 | dept/legal.mlog ×2, dept/design.mlog ×2 | `join(parts," ",F,length(parts))` — 4 арг при 2-арг | `join(slice(parts, F, length(parts)), " ")` — slice end-эксклюзивен (проба: `slice([a,b,c,d],1,4)` → `b|c|d`) |
| 8 | dept/engineering.mlog | `SearchArchive(parsed.discipline, 20)` — 2 арг; глобально побеждал utils-1-арг | паттерн переименован `EngineeringSearchArchive` (def + вызов + докстринг) |
| 9 | dept/qa.mlog | `EnforceHardRules(query, environment, "project", sensitiveFeatures)` — 4 арг; глобально побеждал legal-3-арг | паттерн переименован `QaEnforceHardRules` (def + вызов + докстринги) |

Переименования (8, 9) — по духу ADR-0014: голос отдела сохранён целиком,
уникальное имя лишь снимает глобальную коллизию; дубли с ОДИНАКОВОЙ
арностью (остальные 6 из реестра ADR-0014) гейту не противоречат и
остаются. Следствие: список дублей ADR-0014 8 → 7 (EnforceHardRules
ушёл; SearchArchive остался дублем legal+utils по 1-арг).

## B. Ремедиация №563: skills-чтения → read_file_or

Skills не в git — восстанавливаются бутстрапом из манифеста; код загрузки
уже нёс graceful-ветку `if s == "" then { …фолбэк… }` — т.е. отсутствие
файла задумано обрабатывать. №563 требует явной формы. Заменено 78 сайтов:
`read_file("skills/…")` → `read_file_or("skills/…", "")` (76 литеральных +
2 динамических в dept/context.mlog, вкл. `skills_index/`). Прочие read_file
(library/, config/, VERSION, report_css.txt и т.п.) НЕ тронуты: файлы
всегда присутствуют в образе (git/бутстрап), громкий отказ при их
отсутствии — честный инцидент-сигнал, ровно то, зачем №563 сделан.

## Верификация (метод каждой цифры)

1. **sha256** — `sha256sum` скачанного артефакта ≡ SHA256SUMS релиза (см. выше).
2. **Версия** — `bin/mlog --version` → `mlog mlog 0.28.0`, grammar rev: 1.
3. **Parse-паритет** — CI-логика (подстрока «parse error»): app.mlog +
   24 dept-файла + dogfood_staging.mlog — 0 parse errors на 0.28.0 И на
   0.27.1 (одинаковый результат).
4. **Audit-паритет** — AUG-копия app.mlog (мост №421): rc=2, 0 `[ERROR]`,
   вывод байт-идентичен 0.27.1 (`diff` пуст); raw app.mlog — «42 errors»
   (тот же долг №327, 0 Category A) — вывод байт-идентичен 0.27.1;
   dept/*.mlog — 0 `[ERROR]` на обоих бинарях (CI-контракт rc∉{0,2} ∨ errors>0).
5. **Serve-бут** — полный стек `scripts/serve_stack.sh` на чистом
   `git archive HEAD`: boot `/health` ok, `/version` ok, webhook /status ok,
   /osp/analyze ping ok, /lz ok, /cron/control ok, /schedules/list —
   полный реестр 23 слотов. До ремедиации A — refusal «Naryad #523:
   semantic findings block serve startup» с ровно 9 находками; после —
   старт чистый.
6. **Функциональный паритет с 0.27.1** — та же батарея на том же коммите:
   идентичные результаты (2 Handler error в обеих — артефакты сэндбокса
   без ключей: TAVILY_API_KEY unset — громкий env ещё с 0.27.1/№481 — и
   parse_json(EOF) от недоступного LLM-прокси; в проде ключи заданы).
7. **Регрессия /repos** — `run_repos_probe.sh` на обоих бинарях, роут под
   веб-гвардом #442 (токен = sha256(CRON_SECRET+":repos")[:16]):
   0.27.1 → HTTP 500 «respond_html() requires an argument at position 1»
   (точный прод-симптом Metalogos-#966); 0.28.0 → HTTP 200, HTML
   «Репозитории — FORGE» построен. Заодно пере-пробован формат
   `redact(…, "hash_only")` на 0.28.0 — токен принят (сверка с
   proxy/routes_tail.py).

## Следствия

1. CI-гвард №312 (audit dept) rides `bin/mlog-0271`; parse-гейты — `bin/mlog` (0.28.0).
2. Гварды версий обновлены: test_n399_a2_llm_757 (0.28.0 + оба sha256),
   test_binary_exec_bit, test_schedules_native, test_fo376_osp_auth,
   test_n384_yana_delegation — пары «боевой+гвард» = (mlog, mlog-0271).
3. test_n449_dedupe: базлайн дублей 8 → 7 (см. A), ADR-0014 дополнен.
4. Деплой владельцем на Render подхватит 0.28.0 автоматически (образ
   собирается из этого Dockerfile); бут-лог ожидание: guard-проба rc=2
   (warnings only), «native schedules OK», /version OK.
5. Р6/Р7 закрываются фактом миграции: прод-регрессия /repos уходит с
   деплоем; апстрим #966 уже закрыт фиксом №565.
