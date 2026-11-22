#!/usr/bin/env python3
"""Мутационная проверка гвардов #741: разбор, дедуп, переключение на
снабженца, ретраи, строка брифа, приём posts[]."""
import shutil
import subprocess

MUTS = [
    ("разбор data-post сломан",
     "proxy/tg_public.py",
     'r\'<div class="tgme_widget_message[^"]*"[^>]*?data-post="([^"/]+)/(\\d+)"\'',
     'r\'<div class="tgme_widget_message_NEVER[^"]*"[^>]*?data-post="([^"/]+)/(\\d+)"\'',
     "tests/test_n741_tg_public.py::test_a1_parse_exilenova_fixture"),
    ("дедуп INSERT OR IGNORE → INSERT",
     "proxy/tg_public.py",
     '"INSERT OR IGNORE INTO lz_channel_posts "',
     '"INSERT INTO lz_channel_posts "',
     "tests/test_n741_tg_public.py::test_a1_store_posts_dedup"),
    ("переключение на снабженца не срабатывает",
     "proxy/tg_public.py",
     'if row and row[0]["fail_count"] >= TG_CHANNEL_FAIL_LIMIT \\',
     'if False and row[0]["fail_count"] >= TG_CHANNEL_FAIL_LIMIT \\',
     "tests/test_n741_tg_public.py::test_a1_channel_fail_switch_to_supply"),
    ("ретрай на любых кодах (не только 50x)",
     "proxy/tg_public.py",
     "TG_PUBLIC_RETRY_CODES = {502, 503, 504}",
     "TG_PUBLIC_RETRY_CODES = {403, 429, 502, 503, 504}",
     "tests/test_n741_tg_public.py::test_a1_fetch_retry_only_on_50x"),
    ("засев без меток #737",
     "proxy/tg_public.py",
     "OSINT_UA_LABELS = {\"origin\": \"UA\", \"ownership\": \"independent\",\n                   \"conflict_party\": \"UA\"}",
     "OSINT_UA_LABELS = {}",
     "tests/test_n741_tg_public.py::test_a2_seed_idempotent"),
    ("валидация posts[] снята",
     "proxy/shop_supply.py",
     "or not str(po.get(\"message_id\") or \"\").strip()",
     "or False",
     "tests/test_n741_tg_public.py::test_b_apply_result_posts"),
    ("строка брифа всегда пустая",
     "proxy/tg_public.py",
     "    try:\n        ensure_schema()\n        ch_rows = _query(",
     "    try:\n        return \"\"\n        ensure_schema()\n        ch_rows = _query(",
     "tests/test_n741_tg_public.py::test_c_monitor_line_ok"),
    ("freshness без TG-поста",
     "proxy/news.py",
     "if tg_latest and (latest is None or str(tg_latest) > str(latest)):",
     "if False:",
     "tests/test_n741_tg_public.py::test_a3_freshness_includes_tg_post"),
]

for name, f, old, new, test in MUTS:
    shutil.copy(f, f + ".bak")
    src = open(f, encoding="utf-8").read()
    if old not in src:
        print(f"ПРОПУЩЕНА-КОНФИГ: {name}")
        shutil.move(f + ".bak", f)
        continue
    open(f, "w", encoding="utf-8").write(src.replace(old, new, 1))
    r = subprocess.run(["python3", "-m", "pytest", test, "-q", "--no-header",
                        "-p", "no:cacheprovider"],
                       capture_output=True, text=True, timeout=300)
    caught = "failed" in r.stdout or "error" in r.stdout
    print(("ПОЙМАНА" if caught else "ПРОПУЩЕНА") + f": {name}")
    shutil.move(f + ".bak", f)
