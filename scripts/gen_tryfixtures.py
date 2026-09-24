#!/usr/bin/env python3
"""№349: генератор try-фикстур — по файлу на кейс, чистый `mlog run` без serve-машинерии.
Идиома офиса: TryVal(try f()) с проверкой to_string(x) == "()" (dept/utils.mlog:415)."""
import os

OUT = "/home/z/my-project/n349-results/tryfix"
os.makedirs(OUT, exist_ok=True)

HEADER = '''pattern TryVal(x: String) -> String {
  return x.value
}

pattern T(x: String) -> String {
'''

FOOTER = '''}

flow Main { input: String = "" -> T -> output }
'''

cases = {
    # 1 json_get успех → значение ключа
    "s1_jsonget_ok": '  let v = TryVal(try json_get("{\\"a\\":\\"ok\\"}", "a"))\n  return "S1=" + to_string(v)',
    # 2 json_get промах по ключу → контракт: "()"
    "f1_jsonget_miss": '  let v = TryVal(try json_get("{\\"a\\":\\"ok\\"}", "nokey"))\n  let m = ""\n  if to_string(v) == "()" then { let m = "F1=()" } else { let m = "F1=" + to_string(v) }\n  return m',
    # 3 parse_json успех + json_get по распарсенному (идиома app.mlog:4126)
    "s2_parsejson_ok": '  let parsed = TryVal(try parse_json("{\\"k\\":\\"v\\"}"))\n  return "S2=" + to_string(json_get(parsed, "k"))',
    # 4 parse_json битый вход → "()"
    "f2_parsejson_bad": '  let v = TryVal(try parse_json("!!!not-json"))\n  let m = ""\n  if to_string(v) == "()" then { let m = "F2=()" } else { let m = "F2=" + to_string(v) }\n  return m',
    # 5 http_get успех (живой локальный сервер :9911) → тело
    "s3_httpget_ok": '  let v = TryVal(try http_get("http://127.0.0.1:9911/ok.txt"))\n  return "S3=" + to_string(v)',
    # 6 http_get мёртвый порт → "()"
    "f3_httpget_dead": '  let v = TryVal(try http_get("http://127.0.0.1:9909/nope"))\n  let m = ""\n  if to_string(v) == "()" then { let m = "F3=()" } else { let m = "F3=" + to_string(v) }\n  return m',
    # 7 RAW без TryVal на успехе: 0.19/0.22 = тело, 0.21 = структура (сломанный контракт)
    "r1_raw_ok": '  return "RAWOK=" + to_string(try http_get("http://127.0.0.1:9911/ok.txt"))',
    # 8 RAW без TryVal на неудаче: 0.19/0.22 = "()", 0.21 = структура
    "r2_raw_fail": '  return "RAWFAIL=" + to_string(try json_get("{\\"a\\":\\"1\\"}", "nokey"))',
    # 9 kv_get отсутствующего ключа через try+TryVal
    "s4_kvget": '  let v = TryVal(try kv_get("n349-missing-key"))\n  return "S4=" + to_string(v)',
    # 10 env отсутствующей переменной через try+TryVal
    "f4_env": '  let v = TryVal(try env("N349_NO_SUCH_VAR"))\n  return "F4=" + to_string(v)',
    # бонус: db-семейство — InitDB-идиома (app.mlog:110), чтение
    "s5_dbquery": '  let v = TryVal(try db_query("SELECT 1 AS one"))\n  return "S5=" + to_string(v)',
}

for name, body in cases.items():
    with open(f"{OUT}/{name}.mlog", "w", encoding="utf-8") as f:
        f.write(HEADER + body + FOOTER)

print(f"generated {len(cases)} fixtures in {OUT}")
