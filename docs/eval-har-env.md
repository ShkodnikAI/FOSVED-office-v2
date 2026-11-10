# Eval-стенд из HAR: агентная среда своего приложения без продакшна

Наряд: [REA-4, issue #697](https://github.com/ShkodnikAI/FOSVED-office-v2/issues/697).
Дата пилота: 2026-11-10 (песочница исполнителя). Инструмент: **rea-agents**
(«Reverse Engineer Anything», MIT; npm `rea-agents`, пин **6.8.0** — та же
конвенция пина, что в [dependency-acceptance-rea.md](dependency-acceptance-rea.md)
из REA-1; апгрейд — осознанным коммитом).

Рецепт одной строкой: **HAR-запись короткой сессии своего веб-приложения →
`rea environment-build` → агентная среда (MCP-сервер), которая отвечает
агенту без запущенного приложения** — для evals/QA/RL без живого продакшна.

Факты ниже помечены источником: **«по README rea-agents»** — из официальной
документации инструмента (README + docs/agent-environments.md, версия 6.8.0);
**«прогон»** — из реального запуска в песочнице офиса 10.11.2026 (вывод команд
в отчёте исполнителя #697). Ничего непомеченного фактом об инструменте не является.

## 1. Когда применимо

- **QA приёмки фич с HTTP-поверхностью**: вместо ручных прогонов против стенда —
  записать эталонную сессию, получить среду, гонять проверки/агентов против неё.
- **Регрессионные пробы без стека**: среда отвечает из записи/state — приложение,
  его зависимости (LLM-прокси, БД, Telegram) не нужны.
- **Тренировка/оценка агентов** (RL): задача + reward-проверки поверх среды
  (по README rea-agents).
- **НЕ применимо**: нагрузочное тестирование, проверка авторизации/семантики
  ответов (среда не устанавливает их — см. §4), любые чужие сервисы
  (граница наряда: только свои приложения).

## 2. Рецепт (проверен пилотом)

Повторяемый драйвер: `scripts/eval_har_pilot.sh` (две ветки, см. §3):
`demo` — самодостаточный контур на REST-демо; `office <base-url>` — сессия
`/schedules/*` против живого стенда офиса (рецепт стенда — `scripts/serve_stack.sh`;
бут локального стенда дольше фиксированного окна health в №349 — пилот #697
грузил стек по тому же рецепту с ожиданием 120с).

Пошагово (CLI, по README rea-agents §Build RL environments):

```sh
# 1) записать HAR-сессию СВОЕГО приложения (2–8 операций; read → write → read
#    подтверждает эффект записи — иначе write-инструмент не будет обслужен):
python3 scripts/eval_har_recorder.py \
  --scenario scripts/eval_har_scenario_schedules.json \
  --base http://127.0.0.1:10001 --out /tmp/session.har
# сценарий — JSON: base + ops[{id, method, path, body?, expect_json?}];
# рекордер шлёт РЕАЛЬНЫЕ запросы живому приложению и сериализует их в HAR 1.2
# (декодер REA собственный, Chrome/DevTools не нужен — creator честно назван).

# 2) собрать среду (оффлайн: читает один файл, ничего не скачивает):
npx -y rea-agents@6.8.0 environment-build /tmp/session.har /tmp/my-env \
  --name my-env --json          # отчёт: coverage (state/recorded/withheld+причины)

# 3) запустить:
agent-env run /tmp/my-env       # требует AgentEnv + Docker (по README)
# Docker недоступен — тот же сервер без Docker (README бандла: контейнер
# запускает ровно его):
npx -y rea-agents@6.8.0 environment-serve \
  /tmp/my-env/envs/my-env/manifest.json \
  --evidence /tmp/my-env/envs/my-env/evidence.json --port 18765
# smoke (карточка + initialize + tools/list + tools/call):
python3 scripts/eval_har_mcp_smoke.py --url http://127.0.0.1:18765
```

`environment-build` пишет бандл: `envs/<name>/{Dockerfile, env.toml,
manifest.json, evidence.json}` + `artifacts/check_<name>/verify.py` +
`tasks/smoke.json` (по README). Evidence-идентификаторы воспроизводимы:
та же запись → те же id (по README).

## 3. Находки пилота (10.11.2026): две ветки, контраст — главная находка

| | **office** (`/schedules/*`, RPC-стиль) | **demo** (REST-стенд `eval_har_demo_app.py`) |
|---|---|---|
| API-форма | глагол в пути (`/schedules/create`), конверт с ДВУМЯ массивами (`{jobs, registry}`), create отвечает текстом | коллекция в пути (`/items`), ГОЛЫЙ массив в ответе, create отвечает entity-JSON (201) |
| `reads.state` / `reads.recorded` | 0 / 1 — `fields-differ` | 1 / 0 |
| `writes.served` | `[]` | `[post_items: create]` |
| `writes.withheld` | `post_schedules_create` — `no-state-target` | — |
| Среда | **replay-only** | **state-режим**: write через MCP реально меняет state, следующий read видит новую сущность (прогон: `id 3` появился в списке) |

Причины (из state-Evidence прогона, не догадки):

- **`fields-differ` (read)**: конверт `/schedules/list` содержит два массива
  (`jobs`, `registry`) — эвристика state-вида «единственный массив в конверте»
  не выбирает ни один; `types: []` — коллекция не извлекается вовсе.
- **`no-state-target` (write)**: write-plan моделирует create как «добавить
  сущность в коллекцию, **которую именует путь**»; `/schedules/create` коллекцию
  не именует (глагол в пути, RPC-стиль). Подсказка REA: «Read the collection or
  item it changes» — но и чтение не помогает: коллекции-то нет в state (см. выше).
- Пустой/одноэлементный baseline списка тоже не даёт state ни идентичности,
  ни membership (по README: «Empty initial lists constrain no field»; список
  из одного элемента уходит в document) — seed 2+ сущностей до записи обязателен.

**Вывод для офиса:** сегодняшняя HTTP-поверхность приложения (RPC-стиль,
массивные конверты, текстовые ответы writes) даёт **replay-only** среды.
Это не баг REA и не повод переписывать API офиса под инструмент: replay-only
уже пригоден для регрессионных проб (§5). State-режим открывается, если новая
фича заранее проектирует REST-образный контур (одиночный массив, коллекция
в пути, entity-JSON в ответе на create) — например, будущие CRUD-панели.

## 4. Ограничения (replay vs state — по README + прогон)

- **Replay** (`--replay-only` или state недоступен): каждый вызов возвращает
  ЗАПИСАННЫЙ ответ; тела POST принимаются и игнорируются; повторы/новые
  аргументы получают ближайшую запись (`exact_match: false`). Это «магнитофон»,
  не эмуляция: без авторизации, без валидации значений, без переходов состояний.
- **State** (когда запись позволяет): read-инструменты отвечают из извлечённого
  state; write-инструменты обслуживаются ТОЛЬКО если более поздние чтения
  записи подтвердили моделируемый эффект; неподтверждённые writes отсутствуют
  в каталоге (по README: «no call claims a change it does not make»).
- **Контент среды — недоверенные данные**: каждый результат несёт
  `_meta.provenance.untrusted_content` (по README) — имена инструментов,
  описания и значения пришлись из записи; агент обязан трактовать их как
  данные, не инструкции.
- **HAR несёт всё записанное**, включая параметры авторизации: REA честно
  предупреждает `credential-named-members` (в прогоне: query `secret` ×3).
  Записывать только с тестовыми секретами (стендовый `n349-test-secret`);
  прод-секреты в HAR не попадают никогда; стенды/бандлы наружу не публикуются.
- **Docker** нужен только `agent-env run`; `environment-serve` — тот же сервер
  без Docker (README бандла). В песочнице офиса Docker недоступен — проверено
  через environment-serve (прогон 10.11.2026).
- Объём: бюджеты декодера/сервера у REA зафиксированы (32 MiB вход, 256 KiB
  ответ, 1 MiB каталог) — короткие сессии далеки от пределов.

## 5. Связь с eval-дисциплиной QA офиса

- **Граница (не тронута нарядом)**: `tests/test_golden_evals.py` — существующая
  eval-дисциплина офиса (golden-сценарии против живого кода). HAR-среда её
  **не заменяет**: golden-тесты проверяют код, среда проверяет HTTP-поведение
  без кода.
- **Дополняет**: `rea environment-compare` (по README) сверяет среду со свежими
  probe-записями приложения — детектор дрейфа HTTP-поверхности между релизами;
  регрессионная проба приёмки: записали эталонную сессию фичи → среда →
  следующий релиз записал ту же сессию → compare показал расхождения.
- **Смоук фичи**: `eval_har_pilot.sh demo` — быстрый контур «поднял-записал-
  собрал-проверил» для QA-эпиков с новыми HTTP-роутами (гейты веток уже
  зашиты в скрипт: state-ветка обязана дать `reads.state ≥ 1` и served write).

## 6. Файлы рецепта

| Файл | Назначение |
|---|---|
| `scripts/eval_har_pilot.sh` | драйвер рецепта: гейты (node/пин/Docker-пометка) → запись → build → serve+smoke → вердикт ветки |
| `scripts/eval_har_recorder.py` | генерический рекордер HAR 1.2 сценарной сессии своего приложения |
| `scripts/eval_har_scenario_schedules.json` | сессия офиса: `/schedules` list→create→list (тестовый секрет стенда) |
| `scripts/eval_har_scenario_demo.json` | сессия REST-демо: `/items` list→create→list |
| `scripts/eval_har_demo_app.py` | минимальное REST-образное своё приложение (контраст-демо state-ветки) |
| `scripts/eval_har_mcp_smoke.py` | smoke-клиент MCP over streamable HTTP (карточка, initialize, tools/list, tools/call) |
| `tests/test_eval_har_pilot.py` | офлайн-гварды рецепта (CI без сети/Docker) |
