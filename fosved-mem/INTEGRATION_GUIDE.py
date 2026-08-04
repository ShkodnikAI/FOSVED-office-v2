"""
═══════════════════════════════════════════════════════════════
FOSVED MEMORY — ИНТЕГРАЦИЯ В llm_proxy.py
═══════════════════════════════════════════════════════════════

Этот файл — Reference. Реальный код добавляется в llm_proxy.py.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ИМПОРТ (добавить в начало llm_proxy.py, после остальных импортов):

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
    from fosved_memory import FosvedMemory

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2. ГЛОБАЛЬНЫЙ ОБЪЕКТ (после импортов):

    # FosvedMemory — persistent typed memory
    _memory_db_path = os.path.join(os.path.dirname(__file__), 'data', 'memory.db')
    os.makedirs(os.path.dirname(_memory_db_path), exist_ok=True)
    memory = FosvedMemory(_memory_db_path)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3. ENDPOINTS (добавить в Flask app):

    @app.route('/memory/recall', methods=['POST'])
    def memory_recall():
        \"\"\"Recall memories by query. Admin-only.\"\"\"
        data = request.get_json(force=True) or {}
        query = data.get('query', '')
        mem_type = data.get('type')
        limit = data.get('limit', 10)
        results = memory.recall(query, type_filter=mem_type, limit=limit)
        return jsonify({'results': results, 'count': len(results)})

    @app.route('/memory/remember', methods=['POST'])
    def memory_remember():
        \"\"\"Save a new memory. Admin-only.\"\"\"
        data = request.get_json(force=True) or {}
        mem_id = memory.remember(
            content=data['content'],
            mem_type=data.get('type', 'fact'),
            confidence=data.get('confidence', 0.8),
            source=data.get('source', 'manual')
        )
        return jsonify({'id': mem_id, 'status': 'remembered'})

    @app.route('/memory/stats', methods=['GET'])
    def memory_stats():
        \"\"\"Memory statistics.\"\"\"
        return jsonify(memory.stats())

    @app.route('/memory/answer', methods=['POST'])
    def memory_answer():
        \"\"\"RAG answer based on memory.\"\"\"
        data = request.get_json(force=True) or {}
        answer_text = memory.answer(data.get('question', ''))
        return jsonify({'answer': answer_text})

    @app.route('/memory/maintenance', methods=['POST'])
    def memory_maintenance():
        \"\"\"Run nightly maintenance. Admin-only.\"\"\"
        result = memory.nightly_maintenance()
        return jsonify({'result': result})

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

4. НОЧНОЙ ЦИКЛ АДМИНА (в admin_night_cycle или эквивалент):

    def admin_memory_maintenance():
        result = memory.nightly_maintenance()
        return result

    # Вызывать из ночного cron:
    # response = memory.nightly_maintenance()
    # Отправить owner результат через Telegram

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

5. СИД (в entrypoint.sh, после первого запуска):

    # Seed memory on first deploy
    if [ ! -f data/memory.db ]; then
        python3 scripts/seed_memory.py data/memory.db
    fi

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

6. ПОРЯДОК ФАЙЛОВ В РЕПО:

    fosved-office-v2/
    ├── lib/
    │   └── fosved_memory.py     # <-- NEW
    ├── scripts/
    │   └── seed_memory.py       # <-- NEW
    ├── data/
    │   └── memory.db            # создастся автоматически при seed
    ├── llm_proxy.py             # добавить импорт + endpoints
    ├── entrypoint.sh            # добавить seed на первый деплой
    ├── .dockerignore            # lib/ НЕ должен быть исключён!
    └── ...

═══════════════════════════════════════════════════════════════
"""