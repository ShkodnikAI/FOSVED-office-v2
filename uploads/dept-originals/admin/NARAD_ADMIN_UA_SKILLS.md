# НАРЯД: Админ — навыки Understand Anything

**Источник:** https://github.com/Egonex-AI/Understand-Anything
**Результат:** Админ получает 6 суб-агентов для глубокого анализа кодовой базы

---

## КОНЦЕПЦИЯ

Understand Anything (UA) — multi-agent система для анализа кода. Адаптируем её архитектуру для Админа: 6 специализированных суб-агентов, каждый отвечает за свою фазу анализа. Работают последовательно в ночном цикле, по запросу — параллельно.

```
/admin analyze
    │
    ├── 1. Scanner    → инвентарь файлов, строк, структуры
    ├── 2. Analyzer   → зависимости, паттерны, вызовы каждого файла
    ├── 3. Grapher    → knowledge graph (nodes + edges)
    ├── 4. Reviewer   → баги, мёртвый код, security, архитектура
    ├── 5. Differ     → impact analysis перед изменениями
    └── 6. Documenter → автодокументация, changelog, guided tours
    │
    ▼
Отчёт → Mini App / утренний brief
```

---

## СУБ-АГЕНТ 1: SCANNER — инвентарь кодовой базы

**Задача:** обойти все файлы, собрать метаданные, построить карту проекта.

```python
def admin_scanner():
    """
    Сканирует проект, возвращает структурированный инвентарь.
    Запускается первым — данные используют остальные суб-агенты.
    """
    inventory = {
        'files': [],
        'total_lines': 0,
        'total_files': 0,
        'by_type': {},  # .mlog, .py, .md, .txt
        'by_dir': {},   # dept/, library/, skills/, config/
    }

    for root, dirs, files in os.walk('/office'):
        # Пропускаем data/, .git/, node_modules/
        dirs[:] = [d for d in dirs if d not in ['data', '.git', 'node_modules', '__pycache__']]
        for f in files:
            path = os.path.join(root, f)
            rel = os.path.relpath(path, '/office')
            try:
                lines = len(open(path).readlines())
            except:
                lines = 0

            ext = os.path.splitext(f)[1]
            dir_name = rel.split('/')[0] if '/' in rel else 'root'

            inventory['files'].append({
                'path': rel,
                'lines': lines,
                'ext': ext,
                'dir': dir_name,
                'size_kb': round(os.path.getsize(path) / 1024, 1),
            })
            inventory['total_lines'] += lines
            inventory['total_files'] += 1
            inventory['by_type'][ext] = inventory['by_type'].get(ext, 0) + 1
            inventory['by_dir'][dir_name] = inventory['by_dir'].get(dir_name, 0) + 1

    return inventory
```

**Вывод Scanner:**
```
SCAN COMPLETE
  Files: 47 | Lines: 8,234 | Size: 1.2 MB
  .mlog: 20 (5,100 lines) | .py: 4 (2,800 lines) | .md: 14 (3,400 lines)
  dept/: 20 files | library/: 14 | skills/: 152 | config/: 16
  Largest: llm_proxy.py (2,087 lines)
  Smallest: config/override_qa.txt (0 lines)
```

---

## СУБ-АГЕНТ 2: ANALYZER — анализ каждого файла

**Задача:** для каждого .mlog и .py файла извлечь: patterns, routes, imports, calls, tables, builtins.

```python
def admin_analyzer(inventory):
    """
    Анализирует каждый файл, извлекает структуру.
    Для .mlog: patterns, routes, imports, builtins, tables
    Для .py: functions, classes, routes, imports
    """
    analysis = []

    for f in inventory['files']:
        if f['ext'] not in ['.mlog', '.py']:
            continue

        content = open(os.path.join('/office', f['path'])).read()
        file_analysis = {
            'path': f['path'],
            'patterns': [],      # pattern Name(...) -> Type
            'routes': [],        # route "/path" method=X
            'imports': [],       # import dept/xxx
            'calls': [],         # имена вызываемых patterns/builtins
            'tables': [],        # CREATE TABLE xxx
            'builtins_used': [], # send_message, query, kv_set...
            'issues': [],        # потенциальные проблемы
        }

        if f['ext'] == '.mlog':
            # Patterns
            for m in re.finditer(r'pattern\s+(\w+)\(([^)]*)\)\s*->\s*(\w+)', content):
                file_analysis['patterns'].append({
                    'name': m.group(1), 'args': m.group(2), 'returns': m.group(3)
                })

            # Routes
            for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                file_analysis['routes'].append({'path': m.group(1), 'method': m.group(2)})

            # Imports
            for m in re.finditer(r'import\s+([\w/]+)', content):
                file_analysis['imports'].append(m.group(1))

            # Builtin calls
            KNOWN_BUILTINS = ['send_message', 'query', 'db_execute', 'kv_set', 'kv_get',
                'http_post', 'http_get', 'read_file', 'write_file', 'call_llm',
                'json_get', 'parse_json', 'json_encode', 'respond', 'respond_html',
                'memorize', 'recall', 'whisper_transcribe', 'tts_send', 'git_push',
                'web_search', 'env', 'now', 'len', 'replace', 'split', 'AuditLog']
            for b in KNOWN_BUILTINS:
                if b + '(' in content:
                    file_analysis['builtins_used'].append(b)

            # Tables
            for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?(\w+)', content):
                file_analysis['tables'].append(m.group(1))

        elif f['ext'] == '.py':
            # Functions
            for m in re.finditer(r'def\s+(\w+)\(', content):
                file_analysis['patterns'].append({'name': m.group(1), 'args': '', 'returns': ''})

            # Flask routes
            for m in re.finditer(r"@\w+\.route\('([^']+)'", content):
                file_analysis['routes'].append({'path': m.group(1), 'method': 'GET/POST'})

        # Pattern calls (вызовы других patterns)
        for p_name in [p['name'] for p in file_analysis['patterns']]:
            for other_file in inventory['files']:
                if other_file['path'] != f['path'] and other_file['ext'] == '.mlog':
                    other_content = open(os.path.join('/office', other_file['path'])).read()
                    if p_name + '(' in other_content:
                        file_analysis['calls'].append({
                            'caller': other_file['path'], 'callee': p_name
                        })

        analysis.append(file_analysis)

    return analysis
```

---

## СУБ-АГЕНТ 3: GRAPHER — knowledge graph

**Задача:** из результатов Analyzer построить граф зависимостей.

```python
def admin_grapher(analysis):
    """
    Строит knowledge graph: nodes (файлы, patterns, routes, tables)
    и edges (imports, calls, reads, creates).
    Сохраняет в SQLite.
    """
    nodes = []
    edges = []

    for fa in analysis:
        # Node: file
        nodes.append({
            'type': 'file', 'name': fa['path'],
            'meta': f"{len(fa['patterns'])} patterns, {len(fa['routes'])} routes"
        })

        # Nodes: patterns
        for p in fa['patterns']:
            nodes.append({'type': 'pattern', 'name': p['name'], 'file': fa['path']})
            # Edge: file → defines → pattern
            edges.append({'source': fa['path'], 'target': p['name'], 'type': 'defines'})

        # Nodes: routes
        for r in fa['routes']:
            nodes.append({'type': 'route', 'name': r['path'], 'file': fa['path']})
            edges.append({'source': fa['path'], 'target': r['path'], 'type': 'exposes'})

        # Nodes: tables
        for t in fa['tables']:
            nodes.append({'type': 'table', 'name': t, 'file': fa['path']})
            edges.append({'source': fa['path'], 'target': t, 'type': 'creates'})

        # Edges: imports
        for imp in fa['imports']:
            edges.append({'source': fa['path'], 'target': imp + '.mlog', 'type': 'imports'})

        # Edges: builtin calls
        for b in fa['builtins_used']:
            edges.append({'source': fa['path'], 'target': b, 'type': 'calls_builtin'})

        # Edges: pattern calls
        for c in fa['calls']:
            edges.append({'source': c['caller'], 'target': c['callee'], 'type': 'calls'})

    # Save to SQLite
    save_graph_to_db(nodes, edges)

    return {'nodes': len(nodes), 'edges': len(edges)}
```

**Визуализация графа (Mini App):**

```html
<!-- SVG или D3.js граф в Mini App -->
<div id="graph-container"></div>
<script>
// Nodes: кружки с цветами по типу (file=серый, pattern=синий, route=зелёный, table=оранжевый)
// Edges: линии с подписями (imports, calls, creates)
// Клик на node → детали
</script>
```

---

## СУБ-АГЕНТ 4: REVIEWER — поиск проблем

**Задача:** 5 категорий проверок.

```python
def admin_reviewer(analysis, graph):
    """
    5 категорий:
    1. ORPHANS — файлы и patterns которые никто не использует
    2. BUGS — undefined calls, type mismatches, crash points
    3. SECURITY — открытые endpoints, SQL injection, XSS
    4. DUPLICATION — похожий код в разных файлах
    5. ARCHITECTURE — нарушения паттернов, tech debt
    """
    findings = []

    # 1. ORPHANS
    all_files = {fa['path'] for fa in analysis}
    imported_files = set()
    for fa in analysis:
        for imp in fa['imports']:
            imported_files.add(imp + '.mlog')

    for f in all_files:
        if f.endswith('.mlog') and f != 'app.mlog' and f not in imported_files:
            findings.append({
                'severity': 'low',
                'category': 'ORPHAN',
                'file': f,
                'issue': f'Файл {f} не импортируется никем — возможно мёртвый код',
                'fix': f'Импортировать в app.mlog или удалить'
            })

    all_patterns = set()
    called_patterns = set()
    for fa in analysis:
        for p in fa['patterns']:
            all_patterns.add(p['name'])
        for c in fa['calls']:
            called_patterns.add(c['callee'])

    for p in all_patterns - called_patterns:
        if p not in ['InitDB', 'Main']:  # entry points
            findings.append({
                'severity': 'low',
                'category': 'ORPHAN',
                'file': '',
                'issue': f'Pattern {p}() определён но нигде не вызывается',
                'fix': 'Вызвать или удалить'
            })

    # 2. BUGS — LLM-анализ (отправляем код на review)
    # Используем call_llm для поиска скрытых багов

    # 3. SECURITY
    for fa in analysis:
        for r in fa['routes']:
            if r['path'].startswith('/cron/'):
                # Проверить что есть проверка CRON_SECRET
                content = open(os.path.join('/office', fa['path'])).read()
                route_section = extract_route_code(content, r['path'])
                if 'CRON_SECRET' not in route_section and 'secret' not in route_section:
                    findings.append({
                        'severity': 'high',
                        'category': 'SECURITY',
                        'file': fa['path'],
                        'issue': f'Route {r["path"]} без проверки CRON_SECRET',
                        'fix': 'Добавить проверку query_param("secret") == env("CRON_SECRET")'
                    })

    # 4. DUPLICATION — LLM-анализ
    # Отправляем пары похожих файлов на сравнение

    # 5. ARCHITECTURE
    for fa in analysis:
        if fa['path'].startswith('dept/') and 'AuditLog' not in fa['builtins_used']:
            findings.append({
                'severity': 'medium',
                'category': 'ARCHITECTURE',
                'file': fa['path'],
                'issue': 'Dispatcher не вызывает AuditLog — действия не логируются',
                'fix': 'Добавить AuditLog() после каждого LLM-вызова'
            })

    return findings
```

---

## СУБ-АГЕНТ 5: DIFFER — impact analysis

**Задача:** перед изменением файла показать что затронуто.

```python
def admin_differ(file_path, graph_edges):
    """
    Показывает impact изменения файла:
    - Какие файлы импортируют этот файл
    - Какие patterns вызывают patterns из этого файла
    - Какие routes затронуты
    - Risk score (low/medium/high)
    """
    dependents = []
    for edge in graph_edges:
        if edge['target'] == file_path or edge['target'] in get_patterns_in_file(file_path):
            dependents.append({
                'file': edge['source'],
                'relation': edge['type'],
            })

    risk = 'low'
    if len(dependents) > 5: risk = 'medium'
    if len(dependents) > 10 or file_path == 'app.mlog': risk = 'high'

    return {
        'file': file_path,
        'dependents': dependents,
        'dependent_count': len(dependents),
        'risk': risk,
        'safe_to_autofix': risk == 'low' and file_path != 'app.mlog',
    }
```

**Пример вывода `/admin impact dept/osp.mlog`:**

```
Impact Analysis: dept/osp.mlog

Зависят от этого файла:
  app.mlog (imports)
  dept/chain.mlog (calls HandleOSP)
  dept/miniapp.mlog (calls SendReport → uses dept colors)

Этот файл зависит от:
  dept/utils.mlog (imports)
  dept/context.mlog (calls BuildContext)

Risk: medium (3 зависимых файла)
Safe to autofix: НЕТ
```

---

## СУБ-АГЕНТ 6: DOCUMENTER — автодокументация

**Задача:** автоматически генерировать/обновлять документацию.

```python
def admin_documenter(inventory, analysis, graph, findings):
    """
    Генерирует:
    1. PROJECT_STRUCTURE.md — карта файлов с описаниями
    2. API_REFERENCE.md — все routes с параметрами
    3. CHANGELOG.md — что изменилось с последнего скана
    4. HEALTH_REPORT.md — здоровье кода (findings summary)
    """

    # 1. PROJECT_STRUCTURE.md
    structure = "# Fosved Office v2 — Структура проекта\n\n"
    structure += f"**{inventory['total_files']} файлов · {inventory['total_lines']} строк**\n\n"
    for f in sorted(inventory['files'], key=lambda x: x['path']):
        structure += f"- `{f['path']}` — {f['lines']} строк\n"

    # 2. API_REFERENCE.md
    api = "# API Reference\n\n"
    for fa in analysis:
        for r in fa['routes']:
            api += f"### `{r['method']} {r['path']}`\n"
            api += f"File: `{fa['path']}`\n\n"

    # 3. CHANGELOG (diff с предыдущим сканом)
    prev_scan = load_previous_scan()
    changelog = generate_changelog(prev_scan, inventory)

    # 4. HEALTH_REPORT
    health = "# Code Health Report\n\n"
    health += f"Score: {calculate_health_score(findings)}/10\n\n"
    health += f"- High: {len([f for f in findings if f['severity']=='high'])}\n"
    health += f"- Medium: {len([f for f in findings if f['severity']=='medium'])}\n"
    health += f"- Low: {len([f for f in findings if f['severity']=='low'])}\n"

    return {
        'structure': structure,
        'api': api,
        'changelog': changelog,
        'health': health,
    }
```

---

## ИНТЕГРАЦИЯ В НОЧНОЙ ЦИКЛ

```python
def admin_night_cycle():
    """
    Полный цикл UA-анализа.
    Запускается /cron/night.
    """
    log("Phase 1/6: Scanner...")
    inventory = admin_scanner()

    log("Phase 2/6: Analyzer...")
    analysis = admin_analyzer(inventory)

    log("Phase 3/6: Grapher...")
    graph = admin_grapher(analysis)

    log("Phase 4/6: Reviewer...")
    findings = admin_reviewer(analysis, graph)

    log("Phase 5/6: Differ...")
    # Impact analysis для файлов изменённых за день
    changed_files = get_recently_changed_files()
    impacts = [admin_differ(f, graph['edges']) for f in changed_files]

    log("Phase 6/6: Documenter...")
    docs = admin_documenter(inventory, analysis, graph, findings)

    # Сохранить результаты
    save_night_report(inventory, analysis, graph, findings, impacts, docs)

    # Автофиксы (только low risk, не app.mlog)
    autofixable = [f for f in findings if f['severity'] == 'low' and 'app.mlog' not in f.get('file', '')]
    applied = apply_autofixes(autofixable)

    # Сформировать summary для утреннего brief
    summary = format_night_summary(inventory, findings, applied, docs)
    kv_set('admin_night_summary', summary)

    return summary
```

---

## НОВЫЕ КОМАНДЫ АДМИНА

```
/admin analyze     → запустить все 6 суб-агентов → отчёт в Mini App
/admin scan        → только Scanner (быстрый инвентарь)
/admin graph       → Grapher + визуализация в Mini App
/admin review      → только Reviewer (поиск проблем)
/admin impact <f>  → Differ для конкретного файла
/admin docs        → Documenter (обновить документацию)
/admin health      → health score (1-10) + top issues
/admin tour        → guided tour по архитектуре (LLM-сгенерированный)
```

---

## `/admin tour` — guided tour

LLM генерирует читаемый обзор архитектуры на основе данных Scanner + Analyzer:

```
Админ: Guided Tour по Fosved Office v2

Офис состоит из 47 файлов (8,234 строки кода).

Сердце системы — app.mlog (1,500 строк). Он принимает все Telegram
сообщения, определяет отдел через DetectDepartment, и вызывает
соответствующий HandleXxx в dept/*.mlog.

Каждый из 14 отделов (dept/*.mlog) загружает профиль из library/*.md,
обогащает контекст через BuildContext (dept/context.mlog), вызывает
LLM через proxy, и отправляет ответ через SendReport (dept/miniapp.mlog).

LLM proxy (llm_proxy.py, 2,087 строк) — самый большой файл. Он
поддерживает 7 провайдеров с failover, генерирует Mini App HTML,
и обрабатывает 15+ endpoints.

Knowledge graph: 847 nodes, 2,341 edges. Самые связанные файлы:
app.mlog (127 edges), llm_proxy.py (89), dept/utils.mlog (45).

Потенциальные проблемы: 3 orphaned файла, 7 unused patterns,
1 незащищённый cron endpoint.

Code health: 7.2/10.
```

---

## КОММИТ

```bash
git commit -m "Admin UA skills: 6 sub-agents (scanner, analyzer, grapher, reviewer, differ, documenter), /admin tour"
git push origin main
```

---

## ОТЧЁТ

```
1. admin_scanner: [✅/❌]
2. admin_analyzer: [✅/❌]
3. admin_grapher: [✅/❌]
4. admin_reviewer (5 categories): [✅/❌]
5. admin_differ: [✅/❌]
6. admin_documenter: [✅/❌]
7. Night cycle integration: [✅/❌]
8. /admin tour: [✅/❌]
9. /admin scan, /admin review, /admin docs: [✅/❌]
10. Knowledge graph в SQLite: [✅/❌]
11. git push: [✅/❌] [хэш]
```
