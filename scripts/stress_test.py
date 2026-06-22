#!/usr/bin/env python3
"""FOSVED Office v2 — Stress Test 85 checks
Static code analysis: files, patterns, commands, integrations, syntax."""
import os, re, sys, json
from pathlib import Path

ROOT = Path(__file__).parent.parent
passed = 0
failed = 0
warnings = 0
results = []

def check(name, condition, detail=""):
    global passed, failed, warnings
    if condition:
        passed += 1
        results.append(f"  ✅ {name}")
    elif detail and "WARN" in detail:
        warnings += 1
        results.append(f"  ⚠️  {name} — {detail}")
    else:
        failed += 1
        results.append(f"  ❌ {name}")

def file_exists(name, path):
    return check(f"{name}: file exists", path.exists(), f"missing {path}")

def file_not_empty(name, path):
    if not path.exists():
        check(name, False, f"missing {path}")
        return
    content = path.read_text()
    check(name, len(content) > 10, f"file too small: {len(content)} bytes")

def has_pattern(name, path, pattern, count=None):
    if not path.exists():
        check(name, False, f"missing {path}")
        return
    content = path.read_text()
    found = len(re.findall(pattern, content, re.DOTALL))
    if count:
        check(name, found >= count, f"expected >= {count}, found {found}")
    else:
        check(name, found > 0, f"pattern not found: {pattern[:40]}")

def no_pattern(name, path, pattern):
    if not path.exists():
        check(name, False, f"missing {path}")
        return
    content = path.read_text()
    found = len(re.findall(pattern, content))
    check(name, found == 0, f"found {found} occurrences of {pattern[:40]}")

print("=" * 60)
print("FOSVED OFFICE v2 — STRESS TEST 85 CHECKS")
print("=" * 60)

# ═══════════════════════════════════════
# GROUP 1: INFRASTRUCTURE (10)
# ═══════════════════════════════════════
print("\n📋 GROUP 1: INFRASTRUCTURE (10)")

file_exists("Dockerfile", ROOT / "Dockerfile")
file_exists("entrypoint.sh", ROOT / "entrypoint.sh")
file_exists("requirements.txt", ROOT / "requirements.txt")
file_exists("reverse_proxy.py", ROOT / "reverse_proxy.py")
file_exists("llm_proxy.py", ROOT / "llm_proxy.py")
file_exists("app.mlog", ROOT / "app.mlog")
file_exists("bin/mlog", ROOT / "bin" / "mlog")
file_exists("README.md", ROOT / "README.md")
file_exists("report_css.txt", ROOT / "report_css.txt")

ep = (ROOT / "entrypoint.sh").read_text() if (ROOT / "entrypoint.sh").exists() else ""
check("entrypoint: llm_proxy(4000)->mlog(10001)->rp(10000)",
      "4000" in ep and "10001" in ep and "10000" in ep)

# ═══════════════════════════════════════
# GROUP 2: DATABASE (8)
# ═══════════════════════════════════════
print("\n📋 GROUP 2: DATABASE TABLES (8)")

tables_check = ["dialog_history", "adapt_corrections", "error_patterns", "miniapp_responses",
          "miniapp_notes", "dept_metrics", "token_usage", "audit_log"]

for t in tables_check:
    has_pattern(f"DB table: {t}", ROOT / "app.mlog", rf"CREATE TABLE.*{t}")

# ═══════════════════════════════════════
# GROUP 3: DEPARTMENT DISPATCHERS (14)
# ═══════════════════════════════════════
print("\n📋 GROUP 3: DEPARTMENT DISPATCHERS (14)")

depts = ["yana", "osp", "lz", "expert", "marketing", "finance", "legal",
         "dev", "design", "qa", "visual", "engineering", "kavalnya", "admin"]

for d in depts:
    file_exists(f"dept/{d}.mlog", ROOT / "dept" / f"{d}.mlog")

# ═══════════════════════════════════════
# GROUP 4: DEPARTMENT HANDLERS (13)
# ═══════════════════════════════════════
print("\n📋 GROUP 4: DEPARTMENT HANDLERS (13)")

handler_names = {
    "yana": "HandleYana", "osp": "HandleOSP", "lz": "HandleLZ",
    "expert": "HandleExpert", "marketing": "HandleMarketing", "finance": "HandleFinance",
    "legal": "HandleLegal", "dev": "HandleDev", "design": "HandleDesign",
    "qa": "HandleQA", "visual": "HandleVisual", "engineering": "HandleEngineering",
    "kavalnya": "HandleKavalnya"
}
for d in depts:
    if d == "admin":
        # Admin has multiple patterns, just check file exists and has patterns
        has_pattern(f"Handler: admin patterns", ROOT / "dept" / "admin.mlog", r"pattern\s+\w+\s*\(", count=3)
        continue
    h = handler_names.get(d, f"Handle{d.capitalize()}")
    has_pattern(f"Handler: {h}", ROOT / "dept" / f"{d}.mlog", rf"pattern\s+{h}\s*\(")

# ═══════════════════════════════════════
# GROUP 5: LIBRARY PROFILES (14)
# ═══════════════════════════════════════
print("\n📋 GROUP 5: LIBRARY PROFILES (14)")

for d in depts:
    file_not_empty(f"library/{d}.md", ROOT / "library" / f"{d}.md")

# ═══════════════════════════════════════
# GROUP 6: SKILLS INDEX (13)
# ═══════════════════════════════════════
print("\n📋 GROUP 6: SKILLS INDEX (13)")

for d in depts:
    file_exists(f"skills_index/{d}.txt", ROOT / "skills_index" / f"{d}.txt")

# ═══════════════════════════════════════
# GROUP 7: CONFIG FILES (15)
# ═══════════════════════════════════════
print("\n📋 GROUP 7: CONFIG FILES (15)")

file_exists("config/priority_model.txt", ROOT / "config" / "priority_model.txt")
file_exists("config/priority_provider.txt", ROOT / "config" / "priority_provider.txt")
for d in depts:
    file_exists(f"config/override_{d}.txt", ROOT / "config" / f"override_{d}.txt")

# ═══════════════════════════════════════
# GROUP 8: SLUG COMMAND ROUTING in proxy (13)
# ═══════════════════════════════════════
print("\n📋 GROUP 8: SLUG COMMANDS IN PROXY (13)")

slug_cmds = {"/yana": "yana", "/osp": "osp", "/lz": "lz", "/expert": "expert",
             "/marketing": "marketing", "/finance": "finance", "/legal": "legal",
             "/dev": "dev", "/design": "design", "/qa": "qa", "/visual": "visual",
             "/engineering": "engineering", "/forge": "kavalnya"}
for cmd, dept in slug_cmds.items():
    has_pattern(f"Proxy: {cmd}->{dept}", ROOT / "llm_proxy.py",
                rf"'{re.escape(cmd)}':\s*'{dept}'")

# ═══════════════════════════════════════
# GROUP 9: COMMANDS IN APP.MLOG (15)
# ═══════════════════════════════════════
print("\n📋 GROUP 9: COMMANDS IN APP.MLOG (15)")

commands_check = [
    ("/start", r'if text == "/start"'),
    ("/help", r'if text == "/help"'),
    ("/status", r'if text == "/status"'),
    ("/lockdown", r'starts_with\(text, "/lockdown"\)'),
    ("/fix", r'starts_with\(text, "/fix"\)'),
    ("/good", r'if text == "/good"'),
    ("/learning", r'if text == "/learning"'),
    ("/debrief", r'starts_with\(text, "/debrief"\)'),
    ("/digest", r'if text == "/digest"'),
    ("/remember", r'starts_with\(text, "/remember"\)'),
    ("/voice", r'starts_with\(text, "/voice"\)'),
    ("/chain", r'starts_with\(text, "/chain"\)'),
    ("/factory", r'starts_with\(text, "/factory"\)'),
    ("/admin", r'starts_with\(text, "/admin"\)'),
    ("/audit", r'if text == "/audit"'),
]

for cmd, pattern in commands_check:
    has_pattern(f"app.mlog: {cmd}", ROOT / "app.mlog", pattern)

# ═══════════════════════════════════════
# GROUP 10: LLM PROVIDERS (7)
# ═══════════════════════════════════════
print("\n📋 GROUP 10: LLM PROVIDERS (7)")

providers = ["zai", "deepseek", "groq", "grok", "anthropic", "openai", "apodex"]
for p in providers:
    has_pattern(f"Provider: {p}", ROOT / "llm_proxy.py", rf'"{p}".*?timeout')

has_pattern("Apodex timeout=300s", ROOT / "llm_proxy.py", r'"apodex".*?300')

# ═══════════════════════════════════════
# GROUP 11: CRON ENDPOINTS (6)
# ═══════════════════════════════════════
print("\n📋 GROUP 11: CRON ENDPOINTS (6)")

cron_routes = ["/cron/morning", "/cron/evening", "/cron/weekly", "/cron/monthly", "/cron/control", "/cron/night"]
for route in cron_routes:
    combined = rf'route\s+"{re.escape(route)}".*?CRON_SECRET'
    has_pattern(f"CRON: {route} + secret", ROOT / "app.mlog", combined)

# ═══════════════════════════════════════
# GROUP 12: DEPT COLORS (3)
# ═══════════════════════════════════════
print("\n📋 GROUP 12: DEPT COLORS (3)")

has_pattern("DeptColorStart if-else", ROOT / "dept/miniapp.mlog", r"pattern\s+DeptColorStart")
has_pattern("DeptColorEnd if-else", ROOT / "dept/miniapp.mlog", r"pattern\s+DeptColorEnd")
has_pattern("DeptName if-else", ROOT / "dept/miniapp.mlog", r"pattern\s+DeptName")

# ═══════════════════════════════════════
# GROUP 13: AUDIT (3)
# ═══════════════════════════════════════
print("\n📋 GROUP 13: AUDIT LOG (3)")

has_pattern("AuditLog pattern", ROOT / "dept/utils.mlog", r"pattern\s+AuditLog\s*\(")
has_pattern("AuditLog in app.mlog (>=15)", ROOT / "app.mlog", r"AuditLog\(", count=15)
has_pattern("AuditLog in proxy (>=10)", ROOT / "llm_proxy.py", r"_log_audit\(", count=10)

# ═══════════════════════════════════════
# GROUP 14: INTEGRATIONS (15)
# ═══════════════════════════════════════
print("\n📋 GROUP 14: INTEGRATIONS (15)")

has_pattern("TTS endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/tts"\)')
has_pattern("STT endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/stt"\)')
has_pattern("Archive publish", ROOT / "llm_proxy.py", r'@app\.post\("/archive/publish"\)')
has_pattern("Archive daily-digest", ROOT / "llm_proxy.py", r'@app\.post\("/archive/daily-digest"\)')
has_pattern("Scheduler morning-brief", ROOT / "llm_proxy.py", r'@app\.post\("/scheduler/morning-brief"\)')
has_pattern("Scheduler evening-summary", ROOT / "llm_proxy.py", r'@app\.post\("/scheduler/evening-summary"\)')
has_pattern("Scheduler weekly-digest", ROOT / "llm_proxy.py", r'@app\.post\("/scheduler/weekly-digest"\)')
has_pattern("Scheduler monthly-review", ROOT / "llm_proxy.py", r'@app\.post\("/scheduler/monthly-review"\)')
has_pattern("Learning fix endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/learning/fix"\)')
has_pattern("Learning good endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/learning/good"\)')
has_pattern("Learning stats endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/learning/stats"\)')
has_pattern("Learning debrief endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/learning/debrief"\)')
has_pattern("Search endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/search"\)')
has_pattern("Voice-set endpoint", ROOT / "llm_proxy.py", r'@app\.post\("/voice-set"\)')
has_pattern("Archive digest", ROOT / "llm_proxy.py", r'@app\.post\("/archive/digest"\)')

# ═══════════════════════════════════════
# GROUP 15: NO REGRESSIONS (5)
# ═══════════════════════════════════════
print("\n📋 GROUP 15: NO REGRESSIONS (5)")

no_pattern("No __replace", ROOT / "app.mlog", r"__replace\(")
no_pattern("No __split", ROOT / "app.mlog", r"__split\(")
no_pattern("No __contains", ROOT / "app.mlog", r"__contains\(")
no_pattern("No TODO in file_cache_skills", ROOT / "file_cache_skills.mlog", r"TODO")
no_pattern("No write_file in DeptName/Color", ROOT / "dept/miniapp.mlog", r"write_file\s*\(")

# ═══════════════════════════════════════
# GROUP 16: FILE_CACHE + MISC (4)
# ═══════════════════════════════════════
print("\n📋 GROUP 16: FILE_CACHE + MISC (4)")

file_not_empty("file_cache.mlog", ROOT / "file_cache.mlog")
file_not_empty("file_cache_skills.mlog", ROOT / "file_cache_skills.mlog")
has_pattern("file_cache: profile patterns", ROOT / "file_cache.mlog", r"pattern\s+fc_library_")
file_exists("data/.gitkeep", ROOT / "data" / ".gitkeep")

# ═══════════════════════════════════════
# GROUP 17: REVERSE PROXY (5)
# ═══════════════════════════════════════
print("\n📋 GROUP 17: REVERSE PROXY (5)")

has_pattern("RP: /miniapp/ -> LLM", ROOT / "reverse_proxy.py", r'"/miniapp/"')
has_pattern("RP: /archive/ -> LLM", ROOT / "reverse_proxy.py", r'"/archive/"')
has_pattern("RP: /cron/ -> MLOG", ROOT / "reverse_proxy.py", r'"/cron/"')
has_pattern("RP: /webhook/ -> MLOG", ROOT / "reverse_proxy.py", r'"/webhook/"')
has_pattern("RP: /scheduler/ -> LLM", ROOT / "reverse_proxy.py", r'"/scheduler/"')

# ═══════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════
print("\n" + "=" * 60)
total = passed + failed + warnings
print(f"RESULTS: {passed}/{total} PASSED  |  {failed} FAILED  |  {warnings} WARNINGS")
print("=" * 60)

if failed > 0:
    print("\nFAILED CHECKS:")
    for r in results:
        if "❌" in r:
            print(f"  {r}")

if warnings > 0:
    print(f"\nWARNINGS ({warnings}):")
    for r in results:
        if "⚠️" in r:
            print(f"  {r}")

# Write JSON result
result = {"passed": passed, "failed": failed, "warnings": warnings, "total": total}
with open(ROOT / "stress_test_result.json", "w") as f:
    json.dump(result, f)

print(f"\nResult saved to stress_test_result.json")
