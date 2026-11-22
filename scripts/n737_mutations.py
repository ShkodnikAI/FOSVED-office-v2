#!/usr/bin/env python3
"""Мутационная проверка гвардов #737: метки, лимит 2/источник, окно,
Tavily-разметка, новые ленты."""
import shutil
import subprocess

MUTS = [
    ("метки ленты потеряны при слиянии БД",
     "proxy/news.py",
     '        reg = RSS_FEEDS.get(r["feed"])',
     '        reg = None',
     "tests/test_n737_src1.py::test_a1_labels_persist_on_collect"),
    ("лимит на источник снят",
     "proxy/news.py",
     "if per_source.get(r[0], 0) >= NEWS_MAX_PER_SOURCE:",
     "if False:",
     "tests/test_n737_src1.py::test_a3_max_per_source"),
    ("окно 500 общих вернулось",
     "proxy/news.py",
     "WHERE rn <= ?\n                      ORDER BY published DESC\"\"\", list(cats) + [NEWS_WINDOW_PER_FEED], fetch=True) or []",
     "ORDER BY published DESC LIMIT 500\"\"\", list(cats), fetch=True) or []",
     "tests/test_n737_src1.py::test_a3_window_per_feed_limits_dominance"),
    ("Tavily-домены не размечаются",
     "proxy/news.py",
     "                    _t_origin, _t_ownership = _tavily_source_labels(url)",
     "                    _t_origin, _t_ownership = \"\", \"\"",
     "tests/test_n737_src1.py::test_a4_tavily_insert_has_labels"),
    ("новые ленты убраны из реестра",
     "proxy/news.py",
     '"kyivindependent": {"url": "https://kyivindependent.com/news-archive/rss/",',
     '"kyivindependent_DISABLED": {"url": "https://kyivindependent.com/news-archive/rss/",',
     "tests/test_n737_src1.py::test_a2_new_feeds_registered"),
    ("префикс метки в выдаче убран",
     "proxy/news.py",
     '        entry = f"[{tag}] {r[0]}: {r[1]}\\n"',
     '        entry = f"{r[1]}\\n"',
     "tests/test_n737_src1.py::test_a4_prefix_labels_in_output"),
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
