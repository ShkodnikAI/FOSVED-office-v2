# Metalogos audit PoCs — main 750e811, release v0.39.0 (sha256 8f9b0e20…)

All probes were run on the PUBLISHED release binary `mlog-linux-x86_64` of v0.39.0.
Secret under test: `SP=TOPSECRET123` (or `HOME_SECRET_PROBE=TOPSECRET123` in folder 5).

| Folder | What it shows | How to run | Expected (secure) | Actual |
|---|---|---|---|---|
| 1_secret_lane | env() secret reaching print / file / network through a helper pattern, a loop, the flow output, a GET URL, a Secret entity | `SP=TOPSECRET123 mlog check pNN.mlog; mlog run pNN.mlog` (q-files: start `python3 listener.py 18123 net.log`, set `METALOGOS_HTTP_ALLOW_PRIVATE=1`) | check refuses | p04, p07, p11, p18, q02–q07, q09, q10: check OK, the secret leaks |
| 2_html_exec_sql_lanes | LLM / request output → respond_html and → exec through helpers | `METALOGOS_MOCK_LLM=1 mlog check X.mlog`; h06: `mlog serve` + `curl '…/a?q=<script>…'` | check refuses | h02, h03, h04, h06, e02, e03 pass; h06 serves the script as text/html. SQL lane (s01–s03) holds |
| 3_loop_label_loss | intraprocedural label loss through the `each` iterator into an outer accumulator | `mlog check l03.mlog` | refuse | l03, l04, l08 pass and leak |
| 4_capability | c02 self-grant; c03 an imported module declares its own `profile capability` and posts; c05 self-approval of cron_run | listener on 18124 | c03 refused (permits belong to the entry program) | c03 posts `data-from-root` |
| 5_check_root_and_test | `mlog check leaf.mlog --root root2.mlog` EXECUTES root2 (prints the secret, writes LEAKED.txt) although `mlog run root2.mlog` refuses it; `mlog test t.mlog` runs the leak with no Category-A gate | as written | no execution / refusal | executed |
| 6_serve | a runtime error text carries the secret value and is returned in the HTTP 500 body | `SP=… METALOGOS_ENV_ALLOWLIST=SP mlog serve e.mlog; curl :18401/err` | generic 500 | `Handler error: … to_int("TOPSECRET123") …` |
| 7_robustness | `mlog check` aborts (stack overflow, SIGABRT) on 50 000 chained `+` or 3 000 nested `if` | `python3 gen.py` | a clean error | abort |
