#!/usr/bin/env python3
"""Мутационная проверка гвардов #739: Beta-сглаживание, справочные строки,
медиана скорости, метка «мало данных», шов Кавальни, оценки не в коде."""
import shutil
import subprocess

MUTS = [
    ("Beta-сглаживание снято",
     "proxy/news.py",
     "return (s + 1.0) / (n + 2.0), n",
     "return (s + 0.0) / (n + 0.0), n if n else (0.0, n)",
     "tests/test_n739_src3.py::test_a1_accuracy_beta_smoothing"),
    ("справочные строки в счёте",
     "proxy/news.py",
     "WHERE r.source = ? AND r.counted = 1\n                       AND e.outcome IN ('confirmed', 'refuted')",
     "WHERE r.source = ?\n                       AND e.outcome IN ('confirmed', 'refuted')",
     "tests/test_n739_src3.py::test_a1_accuracy_excludes_uncounted_and_pending"),
    ("скорость — не медиана",
     "proxy/news.py",
     "med = lags[k // 2] if k % 2 else (lags[k // 2 - 1] + lags[k // 2]) / 2.0",
     "med = lags[0] if lags else None",
     "tests/test_n739_src3.py::test_a1_speed_median_lag"),
    ("пометка «мало данных» снята",
     "proxy/news.py",
     '    if n < 10:\n        tail += ", мало данных"',
     "    if False:\n        pass",
     "tests/test_n739_src3.py::test_a4_label_suffix_format"),
    ("метка рейтинга убрана из выдачи",
     "proxy/news.py",
     "        _rating = source_label_suffix(r[0])\n        if _rating:\n            tag += _rating",
     "        pass",
     "tests/test_n739_src3.py::test_a4_label_in_fresh_news_output"),
    ("шов Кавальни удалён",
     "dept/kavalnya.mlog",
     'call_python("news", "register_resolved_event"',
     'call_python("news", "register_disabled"',
     "tests/test_n739_src3.py::test_a3_kavalnya_seam_exists"),
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
