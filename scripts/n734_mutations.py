#!/usr/bin/env python3
"""Мутационная проверка гвардов #734: отсечка 48 ч, архивный блок, лимит 3,
capped-пометка, miniapp-сохранение, audit capped."""
import shutil
import subprocess

MUTS = [
    ("отсечка 48 ч снята",
     "dept/scheduler.mlog",
     "CASE WHEN created_at IS NOT NULL AND created_at < datetime('now','-48 hours') THEN 1 ELSE 0 END AS stale",
     "CASE WHEN 0 THEN 1 ELSE 0 END AS stale",
     "tests/test_n734_report_caps.py::TestLiveFixture::test_a1_arch_scenario"),
    ("архивный блок удалён",
     "dept/scheduler.mlog",
     'let arch_block = "— архив —\\n" + arch_line',
     'let arch_block = "placeholder\\n"',
     "tests/test_n734_report_caps.py::TestLiveFixture::test_a1_arch_scenario"),
    ("лимит 3 снят",
     "dept/scheduler.mlog",
     "pattern OutboxMaxParts() -> Float {\n  return 3.0\n}",
     "pattern OutboxMaxParts() -> Float {\n  return 100.0\n}",
     "tests/test_n734_report_caps.py::TestLiveFixture::test_a2_cap_scenario"),
    ("capped-пометка без числа",
     "dept/scheduler.mlog",
     'let capped_text = "🌙 Ночной отчёт (часть " + to_string(to_int(OutboxMaxParts())) + ")\\nОтчёт не поместился: ещё " + to_string(to_int(more)) + " частей"',
     'let capped_text = "🌙 Ночной отчёт: не поместился"',
     "tests/test_n734_report_caps.py::TestLiveFixture::test_a2_cap_scenario"),
    ("полный текст не сохраняется",
     "dept/scheduler.mlog",
     '"night report", full_text, "", ""]',
     '"night report", "", "", ""]',
     "tests/test_n734_report_caps.py::TestLiveFixture::test_a2_cap_scenario"),
    ("audit без capped-пометки",
     "dept/scheduler.mlog",
     ' + " capped=1 archived_rows=" + to_string(to_int(arch_n)) + " doc=" + doc_id)',
     ' + " doc=" + doc_id)',
     "tests/test_n734_report_caps.py::TestLiveFixture::test_a2_cap_scenario"),
    ("архивные строки в Telegram",
     "dept/scheduler.mlog",
     '      let full_text = full_text + "— " + src + " — (" + cat + ")\\n" + txt\n    } else {',
     '      let block = "— " + src + " —\\n" + txt\n      let arr3 = parse_json(OutboxSplitChunks(block, 3400.0))\n      each piece3 in arr3 {\n        let pc3 = to_string(piece3)\n        if length(pc3) > 0.0 then {\n          let all_json = all_json + json_encode(pc3) + ","\n          let total = total + 1.0\n        }\n      }\n      let full_text = full_text + "— " + src + " — (" + cat + ")\\n" + txt\n    } else {',
     "tests/test_n734_report_caps.py::TestLiveFixture::test_a1_arch_scenario"),
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
