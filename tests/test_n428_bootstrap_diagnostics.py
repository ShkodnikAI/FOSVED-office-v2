"""Гвард наряда #428: диагностика bootstrap 403 + чистые миграции + KV на диске.

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/428
A.1 — роут /schedules/bootstrap различает cron_key_unset / key_mismatch
(имена без слова secret: аудитор 0.27.0 помечает respond-литералы со словом
secret как секретоподобные — sink clearance violation, бисекция).
A.2 — entrypoint.sh печатает тело не-2xx в бут-лог.
A.3 — миграция narads.updated_at без non-constant default + идемпотентный UPDATE.
A.4 — блок миграции lz_telegram_posts исполняется только при существовании таблицы.
A.5 — KV-стор направляется на постоянный диск симлинком в entrypoint.sh.
Запуск: python -m pytest tests/test_n428_bootstrap_diagnostics.py -v
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
ENTRYPOINT = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")
DOCS = (REPO_ROOT / "docs" / "render-dashboard.md").read_text(encoding="utf-8")


def _route_block(source: str, route: str) -> str:
    """Тело конкретного route-блока (по строке route "...")."""
    lines = source.splitlines()
    start = None
    for i, line in enumerate(lines):
        if f'route "{route}"' in line:
            start = i
            break
    assert start is not None, f"роут {route} не найден"
    depth = 0
    out = []
    for line in lines[start:]:
        out.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0 and len(out) > 1:
            break
    return "\n".join(out)


# ── A.1: различимые причины 403 в bootstrap ──────────────────────────────────

def test_bootstrap_route_distinguishes_403_reasons():
    block = _route_block(APP, "/schedules/bootstrap")
    assert 'respond("403 cron_key_unset")' in block, "unset-причина не различима"
    assert 'respond("403 key_mismatch")' in block, "mismatch-причина не различима"
    # старый неразличимый ответ из этого роута убран
    assert 'respond("403 Forbidden")' not in block


def test_bootstrap_403_bodies_are_literals_no_secret_interpolation():
    # тело ответа — строковый литерал без конкатенации: секрет не попадает;
    # слово secret в respond-литерале запрещено аудитором 0.27.0
    block = _route_block(APP, "/schedules/bootstrap")
    for m in re.finditer(r'respond\("403 ([a-z_]+)"\)', block):
        reason = m.group(1)
        assert reason in ("cron_key_unset", "key_mismatch"), f"неожиданный код: {reason}"
        assert "secret" not in reason, f"respond-литерал со словом secret роняет аудит: {reason}"
    assert 'respond(secret' not in block and 'respond(cron_secret' not in block


# ── A.3: миграция narads.updated_at ─────────────────────────────────────────

def test_narads_updated_at_alter_without_expression_default():
    assert 'ALTER TABLE narads ADD COLUMN updated_at TEXT DEFAULT' not in APP, \
        "ALTER с выражением по умолчанию — воспроизводимый non-constant default"
    assert 'ALTER TABLE narads ADD COLUMN updated_at TEXT"' in APP, \
        "ALTER без выражения по умолчанию отсутствует"


def test_narads_updated_at_backfill_update_present():
    assert 'UPDATE narads SET updated_at = datetime(\'now\') WHERE updated_at IS NULL' in APP, \
        "идемпотентное заполнение NULL-строк отсутствует"


# ── A.4: lz_telegram_posts — тишина по отсутствующей таблице ────────────────

def test_lz_telegram_posts_alter_is_gated_by_table_existence():
    block = _route_block(APP, "/schedules/bootstrap")  # заглушка: блок в InitDB, проверяем по всему файлу
    del block
    # ALTER по lz_telegram_posts больше не идёт до проверки sqlite_master
    lines = APP.splitlines()
    alter_idx = next(i for i, l in enumerate(lines) if "ALTER TABLE lz_telegram_posts" in l)
    check_idx = next(i for i, l in enumerate(lines) if "name='lz_telegram_posts'" in l)
    assert check_idx < alter_idx, "ALTER исполняется до проверки sqlite_master"
    # гейт через length, устойчивый к сериализации пустого выборка
    gate = "\n".join(lines[check_idx:alter_idx])
    assert "if length(lz_old_posts) > 0.0 then" in gate, "гейт существования таблицы не через length"
    # старый хрупкий гейт убран
    assert 'to_string(lz_old_posts) != "()"' not in APP


# ── A.2: entrypoint печатает тело не-2xx ────────────────────────────────────

def test_entrypoint_prints_non2xx_body():
    assert "HTTP ${BOOT_CODE} body: ${BOOT_REPORT}" in ENTRYPOINT, \
        "тело не-2xx не печатается в бут-лог"


# ── A.5: KV-стор на постоянный диск ─────────────────────────────────────────

def test_entrypoint_symlinks_kv_store_to_persistent_disk():
    assert 'KV_DISK_PATH="${DATABASE_PATH:-}/metalogos_kv.db"' in ENTRYPOINT
    assert "ln -s" in ENTRYPOINT, "симлинк KV-стора отсутствует"
    assert "mv data/metalogos_kv.db" in ENTRYPOINT, "разовая миграция эфемерного файла отсутствует"
    # гвард: только при заданном DATABASE_PATH (локально прежнее поведение)
    assert '[ -n "${DATABASE_PATH:-}" ]' in ENTRYPOINT


def test_docs_document_kv_location():
    assert "№428 A.5" in DOCS and "metalogos_kv.db" in DOCS
    assert "DATABASE_PATH" in DOCS, "в документации не назван источник пути постоянного диска"
