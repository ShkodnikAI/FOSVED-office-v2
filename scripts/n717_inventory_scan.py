#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""n717_inventory_scan.py — машинный инвентарь потоков секретов/LLM/ввода (наряд #717 SEC-1, п.1).

Метод (AGENTS.md §1 — код источник правды, не проза):
  1. Сканирует производственную поверхность .mlog: app.mlog, dogfood_staging.mlog,
     dept/*.mlog, library/*.mlog, memories/*.mlog (test_*.mlog корня — фикстуры,
     вне инвентаря; test-блоки внутри файлов в граф вызовов не входят).
  2. Мини-лексер: комментарии -> пробелы, содержимое строковых литералов -> 'S'
     (позиции сохраняются) — скобки считаются честно, находки не рождаются
     в строках/комментариях. Имена env-переменных снимаются с оригинала.
  3. Источники в теле паттерна: env( / env_or( (секреты и конфиг; имена
     переменных — отдельно), call_llm( (вывод LLM), json_body( /
     query_param( (ввод запроса).
  4. Стоки в теле: send_message, http_post, http_get, exec, write_file, print,
     respond, respond_html.
  5. Граф вызовов паттернов (глобальные имена — как их видит --root-флэттен);
     поток = источник-паттерн, достижимый из сток-паттерна; для каждой пары
     кратчайший путь. Интра-процедурные потоки (источник и сток в одном теле)
     учитываются отдельно — их интра-процедурный аудитор видит уже сегодня.
  6. redact на call-site — эвристика «в той же строке», в доке помечена
     эвристикой; обязательная колонка «нужен ли redact/аннотация» —
     курируемая (по трассировкам §5–§7).

Режимы:
  python3 scripts/n717_inventory_scan.py            # сводка в stdout
  python3 scripts/n717_inventory_scan.py --json     # полный JSON
  python3 scripts/n717_inventory_scan.py --md       # markdown-фрагменты §2–§4
Используется tests/test_n717_sec1.py: инвентарь docs/office/interproc_inventory.md
не может разойтись с живым кодом (числа сверяются машиной).
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import deque

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRODUCTION_FILES = (
    ["app.mlog", "dogfood_staging.mlog"]
    + sorted(glob.glob(os.path.join(REPO, "dept", "*.mlog")))
    + sorted(glob.glob(os.path.join(REPO, "library", "*.mlog")))
    + sorted(glob.glob(os.path.join(REPO, "memories", "*.mlog")))
)

SINK_BUILTINS = ["send_message", "http_post", "http_get", "exec",
                 "write_file", "print", "respond", "respond_html"]
SOURCE_RE = {
    "env": re.compile(r"\benv\("),
    "env_or": re.compile(r"\benv_or\("),
    "llm": re.compile(r"\bcall_llm\("),
    "json_body": re.compile(r"\bjson_body\("),
    "query_param": re.compile(r"\bquery_param\("),
}
ENV_NAME_RE = re.compile(r"\benv(?:_or)?\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\"")
PATTERN_HDR = re.compile(r"(?:^|\n)[ \t]*pattern\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
ROUTE_HDR = re.compile(r"(?:^|\n)[ \t]*route\s+\"")
CONFIG_HDR = re.compile(r"(?:^|\n)[ \t]*(llm|db|memory)\s*\{")
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def mask_code(src):
    """Комментарии -> пробелы, содержимое строк -> 'S'; позиции и \\n сохраняются."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch == '/' and i + 1 < n and src[i + 1] == '/':
            j = i
            while j < n and src[j] != '\n':
                out[j] = ' '
                j += 1
            i = j
            continue
        if ch == '"':
            j = i + 1
            out[i] = '"'
            while j < n and src[j] != '"':
                if src[j] == '\\' and j + 1 < n:
                    out[j] = out[j + 1] = 'S'
                    j += 2
                    continue
                if src[j] != '\n':
                    out[j] = 'S'
                j += 1
            if j < n:
                out[j] = '"'
            i = j + 1
            continue
        i += 1
    return ''.join(out)


def find_blocks(masked, hdr_re):
    """[(header_text, start_line, end_line, start_off, end_off)] — имена из заголовка
    возвращает как есть (в masked), для оригинала caller берёт срез из src."""
    blocks = []
    for m in hdr_re.finditer(masked):
        # строка заголовка: матч может начинаться с \n — текст заголовка на строке ниже
        hdr_start = m.start() + (1 if masked[m.start()] == '\n' else 0)
        brace = masked.find('{', m.end() - 1)
        if brace == -1:
            continue
        depth, k = 0, brace
        while k < len(masked):
            if masked[k] == '{':
                depth += 1
            elif masked[k] == '}':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if depth != 0:
            continue
        blocks.append((m.group(0), masked.count('\n', 0, hdr_start) + 1,
                       masked.count('\n', 0, k) + 1, m.start(), k))
    return blocks


def scan():
    patterns = {}
    routes = []
    config_blocks = []
    for path in PRODUCTION_FILES:
        src = open(path, encoding='utf-8').read()
        masked = mask_code(src)
        rel = os.path.relpath(path, REPO)
        for hdr, ln0, ln1, s, e in find_blocks(masked, PATTERN_HDR):
            name = re.search(r"pattern\s+([A-Za-z_][A-Za-z0-9_]*)", hdr).group(1)
            body_masked = masked[s:e]
            body_src = src[s:e]
            entry = {
                "file": rel, "line": ln0, "end_line": ln1,
                "sources": sorted(k for k, rx in SOURCE_RE.items() if rx.search(body_masked)),
                "env_vars": sorted(set(ENV_NAME_RE.findall(body_src))),
                "sinks": sorted(b for b in SINK_BUILTINS if re.search(r"\b%s\(" % b, body_masked)),
                "calls": sorted({cm.group(1) for cm in CALL_RE.finditer(body_masked)
                                 if cm.group(1) not in SOURCE_RE
                                 and cm.group(1) not in SINK_BUILTINS
                                 and cm.group(1) not in ("if", "while", "return", "try")}),
                "redact_lines": {masked.count('\n', 0, m.start()) + 1
                                 for m in re.finditer(r"\bredact\s*\(", body_masked)},
            }
            # эвристика redact на call-site: строки, где есть и redact(, и вызов
            redact_call_lines = set()
            for cm in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", body_masked):
                ln = masked.count('\n', 0, cm.start()) + 1
                if ln in entry["redact_lines"] and cm.group(1) != "redact":
                    redact_call_lines.add((cm.group(1), ln))
            entry["redact_calls"] = sorted(redact_call_lines)
            patterns.setdefault(name, []).append(entry)
        for hdr, ln0, ln1, s, e in find_blocks(masked, ROUTE_HDR):
            body = masked[s:e]
            # имя маршрута — из оригинала, до конца строки заголовка (в masked оно 'S')
            eol = src.find('\n', s + 1)
            orig_hdr = src[s:eol if eol != -1 else e]
            rm = re.search(r"route\s+\"([^\"]+)\"", orig_hdr)
            routes.append({
                "file": rel, "route": rm.group(1) if rm else "?", "line": ln0,
                "sources": sorted(k for k, rx in SOURCE_RE.items() if rx.search(body)),
                "sinks": sorted(b for b in SINK_BUILTINS if re.search(r"\b%s\(" % b, body)),
            })
        for hdr, ln0, ln1, s, e in find_blocks(masked, CONFIG_HDR):
            body_src = src[s:e]
            envs = sorted(set(ENV_NAME_RE.findall(body_src)))
            if envs:
                config_blocks.append({
                    "kind": re.search(r"(llm|db|memory)", hdr).group(1),
                    "file": rel, "line": ln0, "env_vars": envs,
                })

    # граф: имя -> вызываемые имена паттернов; обратный: имя -> кто зовёт
    graph = {name: sorted({c for e in ents for c in e["calls"] if c in patterns})
             for name, ents in patterns.items()}
    rgraph = {}
    for caller, callees in graph.items():
        for callee in callees:
            rgraph.setdefault(callee, []).append(caller)

    def shortest_path(a, b):
        """Путь ЗНАЧЕНИЯ: a <- вызывающий <- ... <- b по обратным рёбрам (a вплывает в b)."""
        q = deque([(a, [a])])
        seen = {a}
        while q:
            cur, path = q.popleft()
            if cur == b:
                return path
            for nxt in rgraph.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, path + [nxt]))
        return None

    source_pats = {n for n, ents in patterns.items() if any(e["sources"] for e in ents)}
    sink_pats = {n for n, ents in patterns.items() if any(e["sinks"] for e in ents)}

    flows, seams = [], {}
    for sname in sorted(source_pats):
        for dname in sorted(sink_pats):
            if dname == sname:
                continue
            path = shortest_path(sname, dname)
            if path:
                flows.append({"source": sname, "sink": dname, "path": path,
                              "direct": len(path) == 2})
                seams.setdefault(sname, set()).add(dname)

    # инtra-процедурные: источник и сток в одном теле — видит аудит сегодня
    intra = []
    for n, ents in patterns.items():
        for e in ents:
            if e["sources"] and e["sinks"]:
                intra.append({"pattern": n, "file": e["file"], "line": e["line"],
                              "sources": e["sources"], "sinks": e["sinks"]})

    # прямые call-site'ы: для каждого сток-паттерна какие источники зовутся напрямую
    direct_edges = []
    for dname in sorted(sink_pats):
        for e in patterns[dname]:
            for callee in e["calls"]:
                if callee in source_pats:
                    wrapped = any(c == callee for c, _ in e["redact_calls"])
                    direct_edges.append({
                        "sink": dname, "sink_file": e["file"], "sink_line": e["line"],
                        "source": callee,
                        "source_defs": [f"{x['file']}:{x['line']}"
                                        for x in patterns[callee]],
                        "sink_builtins": e["sinks"],
                        "redact_at_call": wrapped,
                    })

    return {
        "files": [os.path.relpath(p, REPO) for p in PRODUCTION_FILES],
        "pattern_count": sum(len(v) for v in patterns.values()),
        "unique_pattern_names": len(patterns),
        "source_patterns": {n: [dict(file=e["file"], line=e["line"], kinds=e["sources"],
                                     env_vars=e["env_vars"]) for e in ents]
                            for n, ents in patterns.items() if any(e["sources"] for e in ents)},
        "sink_patterns": {n: [dict(file=e["file"], line=e["line"],
                                   builtins=e["sinks"]) for e in ents]
                          for n, ents in patterns.items() if any(e["sinks"] for e in ents)},
        "routes": routes,
        "config_blocks": config_blocks,
        "flows": flows,
        "seams": {k: sorted(v) for k, v in sorted(seams.items())},
        "intra": intra,
        "direct_edges": direct_edges,
        "env_readers": {n: sorted({v for e in ents for v in e["env_vars"]})
                        for n, ents in patterns.items()
                        if any(e["env_vars"] for e in ents)},
    }


def md_fragments(d):
    """Markdown-фрагменты для docs/office/interproc_inventory.md (§2)."""
    out = []
    # §2.0 конфиг-блоки
    out.append("### 2.0 Конфиг-блоки верхнего уровня: env вне паттернов (%d)\n" % len(d["config_blocks"]))
    out.append("Ключи провайдеров LLM и DATABASE_URL читает сама конфигурация рантайма "
               "(`llm { providers: [...] }`, `db { url: ... }`) — вне тел паттернов; "
               "интра-процедурный аудит паттернов их не видит вообще.\n")
    out.append("| Блок | Файл:строка | env-переменные |")
    out.append("|---|---|---|")
    for c in d["config_blocks"]:
        out.append("| `%s` | %s:%d | %s |" % (c["kind"], c["file"], c["line"],
                                              ", ".join("`%s`" % v for v in c["env_vars"])))
    out.append("")
    # §2 источники
    out.append("### 2.1 Паттерны-источники: env / env_or (%d)\n" % len(d["env_readers"]))
    out.append("| Паттерн | Файл:строка | env-переменные | Вид |")
    out.append("|---|---|---|---|")
    for n in sorted(d["env_readers"]):
        for e in d["source_patterns"].get(n, []):
            if "env" in e["kinds"] or "env_or" in e["kinds"]:
                out.append("| `%s` | %s:%d | %s | %s |" % (
                    n, e["file"], e["line"],
                    ", ".join("`%s`" % v for v in e["env_vars"]) or "—",
                    "env" if "env" in e["kinds"] else "env_or"))
    llm_src = [n for n, ents in d["source_patterns"].items()
               if any("llm" in e["kinds"] for e in ents)]
    out.append("\n### 2.2 Паттерны-источники: вывод LLM — call_llm (%d)\n" % len(llm_src))
    out.append("Возврат call_llm наружу; полный список имён — в JSON-выгрузке сканера "
               "(регенерация: `python3 scripts/n717_inventory_scan.py --json`). "
               "Ключевые швы-обёртки: `LZLlm` (dept/lz_seam.mlog:16), `CallLLMProxy`/"
               "`CallLLMResilient` (app.mlog), `KKAskForDept` (app.mlog:5819), "
               "хендлеры отделов (`HandleLZ`, `HandleOSP`, `HandleAdmin`, …).")
    input_src = [n for n, ents in d["source_patterns"].items()
                 if any(("json_body" in e["kinds"] or "query_param" in e["kinds"]) for e in ents)]
    out.append("\n### 2.3 Паттерны-источники: ввод запроса — json_body / query_param (%d)\n"
               % len(input_src))
    out.append("| Паттерн | Файл:строка | Вид |")
    out.append("|---|---|---|")
    for n in sorted(input_src):
        for e in d["source_patterns"][n]:
            if "json_body" in e["kinds"] or "query_param" in e["kinds"]:
                kinds = [k for k in e["kinds"] if k in ("json_body", "query_param")]
                out.append("| `%s` | %s:%d | %s |" % (n, e["file"], e["line"], ", ".join(kinds)))
    # §3 стоки
    out.append("\n### 2.4 Паттерны-стоки (%d уникальных имён)\n" % len(d["sink_patterns"]))
    out.append("| Паттерн | Файл:строка | Стоки |")
    out.append("|---|---|---|")
    for n in sorted(d["sink_patterns"]):
        for e in d["sink_patterns"][n]:
            out.append("| `%s` | %s:%d | %s |" % (n, e["file"], e["line"],
                                                  ", ".join(e["builtins"])))
    # §4 потоки: прямые рёбра источник->сток
    out.append("\n### 2.5 Прямые рёбра «источник → сток» (%d; redact — эвристика той же строки)\n"
               % len(d["direct_edges"]))
    out.append("| Источник | Сток-паттерн | Сток-библиотеки | redact на call-site |")
    out.append("|---|---|---|---|")
    for e in d["direct_edges"]:
        out.append("| `%s` | `%s` (%s:%d) | %s | %s |" % (
            e["source"], e["sink"], e["sink_file"], e["sink_line"],
            ", ".join(e["sink_builtins"]),
            "да" if e["redact_at_call"] else "**нет**"))
    # интра-процедурные
    out.append("\n### 2.6 Интра-процедурные потоки — источник и сток в одном теле (%d)\n"
               % len(d["intra"]))
    out.append("Эти потоки интра-процедурный аудит видит уже сегодня (базовая линия #633).\n")
    out.append("| Паттерн | Файл:строка | Источники | Стоки |")
    out.append("|---|---|---|---|")
    for e in d["intra"]:
        out.append("| `%s` | %s:%d | %s | %s |" % (
            e["pattern"], e["file"], e["line"],
            ", ".join(e["sources"]), ", ".join(e["sinks"])))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="полный JSON в stdout")
    ap.add_argument("--md", action="store_true", help="markdown-фрагменты §2 в stdout")
    args = ap.parse_args()
    data = scan()
    if args.json:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=1, sort_keys=True)
        return
    if args.md:
        sys.stdout.write(md_fragments(data))
        return
    print("файлов: %d, паттернов: %d (уникальных имён: %d)" % (
        len(data["files"]), data["pattern_count"], data["unique_pattern_names"]))
    print("источников-паттернов: %d (env-читателей: %d, LLM: %d, ввод: %d)" % (
        len(data["source_patterns"]), len(data["env_readers"]),
        sum(1 for n, e in data["source_patterns"].items()
            if any("llm" in x["kinds"] for x in e)),
        sum(1 for n, e in data["source_patterns"].items()
            if any(("json_body" in x["kinds"] or "query_param" in x["kinds"]) for x in e))))
    print("стоков-паттернов: %d" % len(data["sink_patterns"]))
    print("маршрутов: %d (с источником: %d, со стоком: %d); конфиг-блоков с env: %d" % (
        len(data["routes"]),
        sum(1 for r in data["routes"] if r["sources"]),
        sum(1 for r in data["routes"] if r["sinks"]),
        len(data["config_blocks"])))
    print("потоков источник→сток (транзитивно): %d, из них прямых рёбер: %d" % (
        len(data["flows"]), len(data["direct_edges"])))
    print("швов (источник, достижимый из стока): %d" % len(data["seams"]))
    print("инtra-процедурных (источник+сток в одном теле): %d" % len(data["intra"]))
    print("env-читатели:")
    for n in sorted(data["env_readers"]):
        defs = "; ".join("%s:%d" % (e["file"], e["line"]) for e in data["source_patterns"].get(n, []))
        print("  %-28s %-44s %s" % (n, defs, ",".join(data["env_readers"][n])))


if __name__ == "__main__":
    main()
