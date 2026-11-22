#!/usr/bin/env python3
"""Мутационная проверка гвардов #755: снятие кэша, тихий curl -sf,
снятие тревоги брифа, снятие поля skills в /version."""
import shutil
import subprocess

MUTS = [
    # (имя, файл, старое, новое, тест)
    ("кэш выключен (шаг 3 удалён)",
     "scripts/bootstrap_skills.sh",
     'CACHE_DIR="${CACHE_ROOT}/${TAG}"',
     'CACHE_DIR="/nonexistent-disabled"',
     "tests/test_n755_skills.py::test_a1_second_start_from_cache_without_token"),
    ("sha-проверка кэша снята",
     "scripts/bootstrap_skills.sh",
     'if [ -n "$EXPECT_SHA" ]; then',
     'if [ -z "$EXPECT_SHA" ]; then',
     "tests/test_n755_skills.py::test_a1_cache_sha_mismatch_falls_to_network"),
    ("HTTP-код заменён молчаливым -sf",
     "scripts/bootstrap_skills.sh",
     'META_CODE=$(curl -sL -o "$TMP_JSON" -w "%{http_code}"',
     'META_CODE=$(curl -sf -o "$TMP_JSON" -w "%{http_code}"',
     "tests/test_n755_skills.py::test_a2_http_code_in_log_401"),
    ("тревога брифа отключена (возврат пустой строки)",
     "proxy/routes_sched.py",
     'if not SKILLS_SENTINEL.is_file():',
     'if False:',
     "tests/test_n755_skills.py::test_a3_attention_item_when_skills_missing"),
    ("вызов skills_line в брифе Яны отключён",
     "proxy/routes_sched.py",
     "            # #755 A.3: навыки отделов — тревога, если сентинела нет\n            skills_line=skills_status_line(),",
     "            skills_line='',",
     "tests/test_n755_skills.py::test_a3_both_call_sites_pass_skills_line"),
    ("поле skills= исчезло из /version",
     "app.mlog",
     '" skills=" + skills_field',
     '""',
     "tests/test_n755_skills.py::test_a3_version_route_has_skills_field"),
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
