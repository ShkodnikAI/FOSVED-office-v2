#!/usr/bin/env python3
"""SEC-3 test: webhook secret token verification in reverse_proxy.py

4 scenarios:
  1. No header → 404
  2. Wrong token → 404
  3. Correct token → not 404 (proxied to Metalogos, may be 5xx but not 404)
  4. WEBHOOK_SECRET empty → not 404 (check disabled)
"""

import os
import sys
import importlib

# ── Patch environment BEFORE importing reverse_proxy ──
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test-secret-123"

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reverse_proxy  # noqa: E402

app = reverse_proxy.app
app.config["TESTING"] = True

PASS = "✅"
FAIL = "❌"

results = []


def run_scenario(name, headers, secret_env, expected_404):
    """Set WEBHOOK_SECRET, send POST /webhook/ with given headers, check result."""
    # Dynamically change the module-level variable
    reverse_proxy.WEBHOOK_SECRET = secret_env

    client = app.test_client()
    resp = client.post("/webhook/", headers=headers, data=b'{"update_id":1}')

    is_404 = resp.status_code == 404
    ok = is_404 == expected_404
    mark = PASS if ok else FAIL
    results.append((name, resp.status_code, mark))
    print(f"  {mark} {name}: status={resp.status_code}  (expected_404={expected_404})")
    return ok


print("\n╔══════════════════════════════════════════╗")
print("║  SEC-3 — Webhook Secret Token Tests       ║")
print("╚══════════════════════════════════════════╝\n")

SECRET = "test-secret-123"
all_ok = True

# Scenario 1: No header → 404
all_ok &= run_scenario(
    "1. No header → 404",
    headers={},
    secret_env=SECRET,
    expected_404=True,
)

# Scenario 2: Wrong token → 404
all_ok &= run_scenario(
    "2. Wrong token → 404",
    headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-value"},
    secret_env=SECRET,
    expected_404=True,
)

# Scenario 3: Correct token → NOT 404
all_ok &= run_scenario(
    "3. Correct token → not 404",
    headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    secret_env=SECRET,
    expected_404=False,
)

# Scenario 4: Secret not set (empty) → NOT 404 (check disabled)
all_ok &= run_scenario(
    "4. Secret not set → not 404",
    headers={},  # no header, but secret is empty so check is skipped
    secret_env="",
    expected_404=False,
)

# ── Summary ──
print(f"\n{'─' * 45}")
total = len(results)
passed = sum(1 for _, _, m in results if m == PASS)
print(f"Result: {passed}/{total} passed")
if all_ok:
    print("SEC-3: ALL TESTS PASSED ✅")
else:
    print("SEC-3: SOME TESTS FAILED ❌")
    sys.exit(1)
