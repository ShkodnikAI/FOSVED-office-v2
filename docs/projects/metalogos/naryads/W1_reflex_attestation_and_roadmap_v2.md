# НАРЯД W1 (v2, после рецензии) — Reflex attestation: сертификат весов и `mlog attest verify`

> Тип: **семантический** (ADR-0110). Выдаётся исполнителю только после того, как владелец принял `ADR-0200-DRAFT-provable-lowering.md` (v2) и завёл issue с дословными решениями (по образцу ADR-0196…0199). Номера наряда и ADR присваивает исполнитель после `git fetch` и `ls docs/adr/`.
> Класс: `[domain]` (AGENTS.md §8.6; без класса рост поверхности реестра = FAIL window verdict) `[ПРОВЕРИТЬ шаблон §8]`.

## Что подтверждено кодом (27.10.2026, не переоткрывать)
- Паритет VM: `reflex_save/load` на VM работают: `src/vm.rs:3296-3304` вызывает те же `reflex_save_dispatch`/`reflex_load_dispatch`, что TW (`execution.rs`). Стабы «VM backend does not yet support Reflex» в `builtins/reflex.rs:69-96` — теневой fallback (прецедент №748).
- Общие точки сохранения/загрузки обоих бэкендов: `save_model_to_db` / `load_model_from_db` в `src/nn/persist.rs`. Хаб `distill_hub.rs` веса сам не пишет: «weights keep persisting through `reflex_save`». Сертификат вешаем на `persist.rs`.
- `metalogos-reflex/src/nn/metric.rs` в манифесте ADR-0178 нет. PyO3 в коде нет (ADR-0013 — только `MockMlBackend`).
- `ledger.rs` не имеет примитива «подписать произвольные байты»; ключ — `METALOGOS_LEDGER_KEY`, без него генерируется случайный на процесс. Поэтому сертификат подписывается **косвенно**: запись ledger `reflex.attest` с `cert_sha256` (подпись ledger Ed25519). Это tamper-evident, не tamper-proof (ADR-0167); так и писать в документации.
- `golden.rs` читает `examples/` нерекурсивно, `examples/distill/` в золотой цикл не попадёт.
- Проверка `feature_signature` уже есть (`persist.rs:391`, №504): только предупреждение в stderr и отказ от distilled-ответов.

## Решения владельца (внести дословно в issue; в наряде — ссылка на него)
1. План «проверяемое понижение яруса» принят. 2. Метрики — только Rust-реестр. 3. Учитель — открытые модели с разрешающей лицензией.
4. *(ожидается, рекомендация ниже)* Переходный режим. 5. *(ожидается)* `attest_verify` на неотфильтрованных данных. 6. *(ожидается)* Выход из `Frozen` только внешней командой.

## Правила
Как в первой версии: код — правда (`grep` до работы); контракт первым; ветка → PR → полный CI (46 джоб); мерж делает владелец; документация на английском; секреты не в отчёты; контур ADR-0178 не растёт (`generative-stop-list` зелёный); без новых `Value`-вариантов; SHA-хелперы переиспользовать (`provenance::sha256_hex`, `ledger::sha256_hex`), не дублировать. При правках `builtins_classification.rs` и label/taint-мест — пункт 10 `docs/risk-review-checklist.md` в описании PR (AGENTS.md §8.5).

## Что построить
**Сертификат** (канонический JSON, ключи отсортированы): `attestation_version`, `model`, `pattern`, `spec_hash`, `data_hash`, `embed_signature`, `weights_sha256`, `teacher{backend, weights_id, license_class, training_on_output_allowed}` (до W3b — `null` с причиной), `dataset{rows, filter, provenance[]}`, `eval{held_out_accuracy, metric, calibration:"uncalibrated"}`, `rollback_if`, `toolchain{reflex_version, mlog_version}`, `ledger_seq`. Чего не знаем — `null` с причиной, не выдумывать. До W4: `dataset.filter = "none"`.

**Три хэша, три кода отказа:**
- `spec_hash` (сигнатура паттерна, нормализованный prompt, labels, `distill_*`, метрика, порог; без комментариев/форматирования/`cache*`) → `[ATTESTATION_STALE]` с **именем изменившегося поля**;
- `data_hash` (манифест обучающего набора) → `[ATTESTATION_DATA_CHANGED]`, информационно, не отказ;
- `embed_signature` → `[ATTESTATION_EMBED_MISMATCH]`, жёсткий отказ.

**Таблица (история, append-only):** `reflex_attestation(seq INTEGER PRIMARY KEY, model, spec_hash, data_hash, embed_signature, weights_sha256, cert_json, ledger_seq, created_at, superseded INTEGER DEFAULT 0)`; текущий сертификат — последняя непомеченная строка модели.

**Поведение:**
- `save_model_to_db`: пишет сертификат и запись ledger `reflex.attest`. Нет настроенного ledger → сертификат с `level: "unsigned"` (только хэши) + громкое предупреждение.
- `load_model_from_db`: проверяет `weights_sha256`, `embed_signature`, `spec_hash`. Веса без сертификата (сохранены до W1) → предупреждение и `cert: none`, загрузка продолжается.
- `METALOGOS_ATTEST_STRICT=1`: отсутствие сертификата и `unsigned` становятся отказами. Через один релиз дефолт переключается на строгий (запись в CHANGELOG Migration).
- Пропуск проверки: CLI `--allow-stale`; для `mlog serve` — `METALOGOS_ATTEST_ALLOW_STALE`. В обоих случаях строка в аудит-логе и запись в ledger.
- Сбой записи в ledger при сохранении: сохранение весов **не** отменяется молча — громкая ошибка (это артефакт, а не побочное действие; в отличие от ADR-0167 для действий) — прописать в ADR-записи о реализации.
- `mlog attest verify <file.mlog> [--model=Name]`: exit 0/1 и причина строкой. Выводит `level`: `unfiltered` (данные до W4), `unsigned`, `signed`.
- Builtin `attest_verify(model) -> Struct{ok, level, spec_hash, reason}` (`spec!()` в `registry.rs`, `builtins_classification.rs`: источник, метка `internal`). Основной путь — VM; TW сверяется в `tests/crosscheck_backends.rs`.

## Файлы `[ПРОВЕРИТЬ grep]`
`src/nn/persist.rs` (точка записи/проверки), `src/builtins/attest.rs` (новый), `src/builtins/reflex.rs`, `src/ledger.rs` (использовать публичный `append_record`/`record`), `src/vision/provenance.rs`, `src/builtins/registry.rs`, `src/builtins_classification.rs`, `metalogos-server/src/` (clap), `src/vm.rs`, TW-путь, `src/distill_hub.rs` (только читать данные для `data_hash`/`dataset`; обучение не менять).

## Контракт-тесты (отдельный файл `tests/naryad_NNN_attest.rs`, не золотой цикл; примеры в `examples/distill/`)
1. save → load → `attest_verify`: `ok: true`, `level: unfiltered`.
2. Правка `prompt` → `ATTESTATION_STALE`, в тексте `prompt`. Правка комментария → сертификат валиден.
3. Подмена байта BLOB → отказ по `weights_sha256`.
4. Смена `embed_signature` → `ATTESTATION_EMBED_MISMATCH`.
5. Веса старого формата без сертификата → предупреждение + `cert: none`; с `METALOGOS_ATTEST_STRICT=1` → отказ.
6. Сертификат после обучения через `distill_hub` в режиме serve и последующего `reflex_save` (путь фонового обучения).
7. Новые данные в `distill_samples` → `DATA_CHANGED` (не отказ).
8. Кросс-проверка VM↔TW.

## Приёмка
1–8 выше зелёные; проверка сертификата < 200 мс (замер приложить); `cargo build --no-default-features` без новых тяжёлых зависимостей, дельта размера бинарника измерена (ADR-0104); существующий golden-корпус не меняет вывод (проверка `tests/golden.rs`, `readme_consistency`, без числа примеров); `generative-stop-list` и check_id (ADR-0140) в порядке; обновлены `REFERENCE.md`, `llms.txt`, метрики README (`gen_metrics.py`, затем `--check`), `CHANGELOG.md` (вердикт по безопасности + Migration); запись о реализации в ADR.

## Не делать
`spec`, `lower`, состояния паттерна, новые метрики, правку грамматики (W2′/W3+). Не менять `reflex_train` и `distill_hub` обучение. Не писать «откалибровано» — до E3 везде `uncalibrated`. Не называть сертификат «доказательством»: он фиксирует происхождение и согласованность, а не качество.

## Отчёт
PR и CI-ссылки; таблица «приёмка → результат»; замеры; итог по каждому `[ПРОВЕРИТЬ]`; что осталось владельцу.

---

# Дорожная карта (с учётом ревизии)

| № | Наряд | Зависит от | Заметка |
|---|---|---|---|
| E1–E4 | Эксперименты (план раунда 2, §9): скорость `embed`, время `reflex_train`, калибровка уверенности, `baseline_agreement` учителя. Результат в `docs/research/` | — | Блокируют W4–W6; можно вести параллельно с W1 |
| W1 | Этот наряд | ADR принят | Первый видимый результат |
| W2′ | Реестр метрик: `macro_f1`, `min_class_recall` (по схеме SSOT №545: код в `metalogos-reflex/src/nn/metric.rs`, реэкспорт из `src/nn/metric.rs`; в манифесте ADR-0178 этого файла нет — подтверждено); правка правила `mutate_rollback` (имя метрики вместо литерала `accuracy`, старая форма остаётся); обязательный majority baseline для гейтящих метрик | — | Вместо старого W2; семантика грамматики, ADR-запись обязательна |
| W3 | Декларация `spec` (грамматика, AST, semantic, компиляция в VM) | W1 | Новое ключевое слово: одно |
| W3b | Реестр учителей: записи LLM-бэкендов с классом лицензии и `training_on_output_allowed`; правило `DISTILL_TEACHER_UNLICENSED` | W3 | Новый наряд, которого не было в плане Е |
| W4 | `mlog curriculum build`: propose-and-refute, held-out без участия учителя | W3, E1 | Строить поверх `distill_hub.rs`; карантин — колонки `reviewed`/`reason`/`quarantined` в `distill_samples`, без новой таблицы |
| W5 | Состояния, гистерезис, cooldown, карантин, `--trace-distill` | W4, E2, E3 | Состояние в VM-owned state |
| W6 | Дифференциальный гейт включения | W5, E4 | Атомарность №530 сохранить |
| W7 | Правила аудита, threat-model, limitations | W3b, W5 | Финальный список check_id — здесь |
| W8 | Документация и индексы | сквозной | |
| W9 | Демо, e2e, бенчмарк | всё | Числа только измеренные |

Резать первым при разрастании: W9 → часть W7 (оставить `DISTILL_TEACHER_UNLICENSED`, `ATTESTATION_STALE`) → cooldown/`Frozen` в W5. Не резать никогда: подпись и проверку сертификата (W1) и held-out, которого учитель не генерировал (W4). Оценка автора «28–33 агентодня» — нижняя граница, закладывать с запасом.
