#!/usr/bin/env python3
"""Мутационная проверка гвардов #738: флаг-дефолт, пометки, Tavily-гейт,
профили, счётчик."""
import shutil
import subprocess

MUTS = [
    ("гейт включён без порога (дефолт 1)",
     "proxy/news.py",
     'os.environ.get("NEWS_RU_CONFIRMATION_GATE", "0") == "1"',
     'os.environ.get("NEWS_RU_CONFIRMATION_GATE", "1") == "1"',
     "tests/test_n738_src2.py::test_gate_disabled_by_default"),
    ("пометки сторон убраны",
     "proxy/news.py",
     '        _mk = _conflict_marks(r)\n        if _mk:\n            entry += _mk + "\\n"',
     "        _mk = \"\"",
     "tests/test_n738_src2.py::test_a2_conflict_party_marked"),
    ("счётчик исключённых убран",
     "proxy/news.py",
     '    if ru_excluded:\n        news_text += (f"Исключено {ru_excluded} сообщений российских СМИ "\n                      f"без подтверждения европейскими источниками\\n")',
     "    if False:\n        pass",
     "tests/test_n738_src2.py::test_a1_counter_with_nonempty_result"),
    ("Tavily-гейт всегда режет (дефолт-гвард снят)",
     "proxy/news.py",
     '    if os.environ.get("NEWS_RU_CONFIRMATION_GATE", "0") != "1":\n        return response_json',
     "    pass",
     "tests/test_n738_src2.py::test_tavily_gate_disabled_by_default"),
    ("профили без правила",
     "library/osp.md",
     "Заявление стороны конфликта без независимого подтверждения — не факт, а позиция стороны",
     "Правило добавлено отдельно (заглушка мутации)",
     "tests/test_n738_src2.py::test_c1_osp_profile_has_rule"),
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
