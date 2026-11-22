#!/usr/bin/env python3
"""#744 EXP-2: рефакторинг dept/expert.mlog.

A.1 гейт дедлайна, брифинги, A.2 LoadExpertSkills (12 несуществующих
скиллов), A.3 подкоманды авто и ExpertAutomotiveKB/SkillSet — удалены
(КБ перенесена в skills/expert/skins/auto/SKIN.md в EXP-1; таблица
expert_briefings не удаляется — данные).

B. Конвейер: профессия (B.1, дешёвый вызов) → шкурка по triggers через
валидатор EXP-1 или черновик в expert_skins_draft (B.2) → план поиска по
8 категориям (B.3) → круги до 12/25 (B.4, честный бюджет Tavily) →
черновик по шаблону 9 разделов (B.5) → разбор «конкурирующим
профессионалом» сильной моделью через llm_verifier.rival_review (B.6,
при недоступности — пометка в отчёте) → инструменты шкурки auto (B.7).

Сигнатуры HandleExpert/ExpertBrief сохранены; маршрутизация app.mlog и
общий TavilySearch не тронуты.
"""
from pathlib import Path

P = Path("dept/expert.mlog")
src = P.read_text(encoding="utf-8")


def cut(start_marker: str, end_marker: str) -> None:
    """Вырезать диапазон [start_marker, end_marker) — оба включительно
    по началу строки-маркера."""
    global src
    i = src.index(start_marker)
    j = src.index(end_marker)
    assert i < j, (start_marker, end_marker)
    src = src[:i] + src[j:]


# ── A: HandleExpert целиком (диспетчер с подкомандами и гейтом) ─────────
new_handle = '''// ═══════════════════════════════════════════════════════════════════════
// MAIN DISPATCHER — #744 EXP-2: подкоманд доменов нет (шкурка надевается
// по запросу); гейта дедлайна нет; брифингов нет. Команды: /expert <тема>,
// /deepexpert <тема> (глубина 25), /expert skin save <id>.
pattern HandleExpert(query: String, chat_id: String) -> String {
  let dept = "expert"
  let t = lower(query)

  // /deepexpert <тема> — флаг глубины: до 25 поисков (решение владельца)
  if starts_with(t, "/deepexpert") then {
    let deep_query = substring(query, 11.0, 300.0)
    return ExpertRunReport(deep_query, chat_id, true)
  }
  // /expert skin save <id> — выдаёт текст SKIN.md черновика (файл не пишет)
  if starts_with(t, "/expert skin save") then {
    let draft_id = substring(query, 17.0, 40.0)
    return ExpertSkinDraftText(draft_id)
  }

  // Default: полный конвейер (до 12 поисков)
  return ExpertRunReport(query, chat_id, false)
}

// ── Константы лимитов поиска (наряд EXP-2 B.4) ──────────────────────────
pattern ExpertSearchMax() -> Float {
  return 12.0
}

pattern ExpertDeepSearchMax() -> Float {
  return 25.0
}

// ── B.1 Профессия: первый дешёвый вызов ────────────────────────────────
// Возвращает строку «Профессия|Специализация|Отрасль|термин1, термин2, …».
// Сбой модели — не остановка: конвейер продолжает с честной пометкой.
pattern ExpertDetectProfession(query: String) -> String {
  let sys = "Определи профессию и узкую специализацию, в которой разбирается профессионал мирового уровня по этому запросу. Ответ строго одной строкой формата: Профессия | Специализация | Отрасль | термин1, термин2, термин3 (3-6 ключевых терминов отрасли для поиска). Ничего кроме строки не пиши."
  let r = redact(to_string(TryVal(try call_llm(sys, query))), "all")
  if to_string(r) == "()" or length(to_string(r)) < 5.0 then {
    return "Профессия не определена | широкая тема | общий | " + substring(query, 0.0, 60.0)
  }
  return to_string(r)
}

// ── B.2 Шкурка: triggers-сопоставление через валидатор EXP-1 ────────────
// Нет готовой → черновик-карточка того же формата в expert_skins_draft.
pattern ExpertPickSkin(query: String, profession_line: String) -> String {
  let resp = TryVal(try call_python("expert_skins", "pick_skin", json_encode([query])))
  if to_string(resp) == "()" then { return "" }
  let parsed = TryVal(try parse_json(to_string(resp)))
  if to_string(parsed) == "()" then { return "" }
  let ok = to_string(json_get(parsed, "ok", "0"))
  if ok == "1" then {
    let skin_md = redact(to_string(json_get(parsed, "skin", "")), "all")
    if length(skin_md) > 0.0 then {
      return "=== Шкурка надета (" + to_string(json_get(parsed, "domain", "?")) + ") ===\\n" + skin_md
    }
    return ""
  }
  // нет готовой шкурки — временная карточка в expert_skins_draft (B.2)
  let draft_sys = "Ты — Эксперт, готовишься надеть профессию. Построй временную карточку шкурки формата SKIN.md (см. README): YAML-фронт domain/professions/triggers/standards/sources/tools + разделы Failure catalog (типовые отказы: что/механизм/как скрывают/серьёзность) и Insider glossary (умная фраза → смысл). Нормы/ГОСТ/ISO — только реально известные и проверяемые; неподтверждаемое помечай «опыт практиков». Это черновик — владелец может сохранить его командой /expert skin save."
  let draft = redact(to_string(TryVal(try call_llm(draft_sys, "Запрос владельца: " + query + "\\nОпределённая профессия: " + profession_line))), "all")
  if to_string(draft) == "()" or length(to_string(draft)) < 50.0 then { return "" }
  let draft_id = "skin-" + to_string(to_float(TryVal(try query("SELECT strftime('%s','now')", [])) != "()" and true and 0.0) == false and 0.0 and 0.0) + "0"
  let _ = ExpertEnsureSkinsDraft()
  let ts_rows = query("SELECT strftime('%s','now') AS ts", [])
  let draft_id = "skin-" + redact(to_string(json_get(get(ts_rows, 0), "ts", "0")), "all")
  let _ = db_execute("INSERT INTO expert_skins_draft (id, topic, json, created_at) VALUES (?, ?, ?, datetime('now'))", [draft_id, substring(query, 0.0, 200.0), draft])
  let _ = AuditLog("expert_skin_draft", "expert", "id=" + draft_id + " topic=" + substring(query, 0.0, 50.0))
  return "=== Черновик шкурки (нет готовой; сохранён в expert_skins_draft id=" + draft_id + ", сохранить: /expert skin save " + draft_id + ") ===\\n" + draft
}

pattern ExpertEnsureSkinsDraft() -> String {
  let _ = TryVal(try db_execute("CREATE TABLE IF NOT EXISTS expert_skins_draft (id TEXT PRIMARY KEY, topic TEXT, json TEXT, created_at TEXT DEFAULT (datetime('now')))", []))
  return "ok"
}

pattern ExpertSkinDraftText(draft_id: String) -> String {
  let _ = ExpertEnsureSkinsDraft()
  let rows = query("SELECT id, topic, json FROM expert_skins_draft WHERE id = ?", [draft_id])
  if length(rows) == 0.0 then { return "Черновик шкурки " + draft_id + " не найден (список черновиков — в таблице expert_skins_draft)." }
  let text = redact(to_string(json_get(get(rows, 0), "json", "")), "all")
  let topic = redact(to_string(json_get(get(rows, 0), "topic", "")), "all")
  let _ = AuditLog("expert_skin_save", "expert", "id=" + draft_id)
  return "Текст SKIN.md черновика " + draft_id + " (тема: " + topic + "). Сохранить файл может владелец — команда файл не пишет:\\n\\n" + text
}

// ── B.3 План поиска по 8 категориям ────────────────────────────────────
// Категории фиксированы нарядом; 1–2 запроса на категорию; языки —
// источники отрасли (en/ru); плюс sources[] шкурки (site:).
pattern ExpertSearchPlan(query: String, profession_line: String, skin_md: String) -> String {
  let cats = "Категории плана поиска (обязательные): 1) нормы и стандарты; 2) статистика отказов, отзывы, рекламации; 3) независимые тесты; 4) форумы и сообщества практиков; 5) научные работы; 6) регуляторы; 7) экономика и цены; 8) критика."
  let sys = "Составь план поиска для профессионального разбора темы. " + cats + "\\nПо каждой категории 1-2 конкретных поисковых запроса; запросы — на языке источников отрасли (en/ru), где уместно — с site: по специализированным источникам. Один запрос на строку, без нумерации и пояснений — только сами запросы."
  let r = redact(to_string(TryVal(try call_llm(sys, "Тема: " + query + "\\nПрофессия: " + profession_line + (if length(skin_md) > 0.0 then "\\n\\nШкурка (sources[] учти в плане):\\n" + substring(skin_md, 0.0, 3000.0) else "")))), "all")
  if to_string(r) == "()" or length(to_string(r)) < 20.0 then {
    // честный фолбэк: статический план по категориям (1 запрос на категорию)
    let q = substring(query, 0.0, 120.0)
    return q + " нормы стандарты\\n" + q + " отзывы рекламации отказы\\n" + q + " независимый тест обзор\\n" + q + " форум практиков опыт\\n" + q + " научная статья исследование\\n" + q + " регулятор требования\\n" + q + " цена стоимость экономика\\n" + q + " критика недостатки подводные камни"
  }
  return to_string(r)
}

// ── B.4 Поиск кругами: круг 1 по плану, круг 2 по пробелам, круг 3 ──────
// только при /deepexpert. Лимит 12/25 на ОТЧЁТ; бюджет Tavily честно.
pattern ExpertSearchCircles(query: String, plan: String, max_searches: Float, chat_id: String, deep: Bool) -> String {
  let used = 0.0
  let mut out = ""
  let mut lines = split(plan, "\\n")
  // ── круг 1: по плану (до половины лимита) ──
  let cap1 = max_searches / 2.0
  each line in lines {
    let q = trim(line)
    if q != "" and used < cap1 then {
      let r = ExpertTavilySearch(q, chat_id)
      let used = used + 1.0
      if r != "" then { let out = out + "\\n[" + q + "]\\n" + r + "\\n" }
    }
  }
  // ── круг 2: модель отмечает непокрытые категории и пустые места ──
  let gap_sys = "План поиска разбора выполнен кругом 1. Отметь непокрытые категории и пустые места: какие факты/цифры/негативные нюансы ещё НЕ закрыты результатами поиска? Сформулируй до 6 конкретных дополнительных поисковых запросов. Один на строку, без пояснений. Если всё закрыто — верни пустой ответ."
  let gaps = redact(to_string(TryVal(try call_llm(gap_sys, "Тема: " + query + "\\nПлан:\\n" + substring(plan, 0.0, 1500.0) + "\\n\\nРезультаты круга 1 (выдержки):\\n" + substring(out, 0.0, 6000.0)))), "all")
  if to_string(gaps) != "()" and length(to_string(gaps)) > 10.0 then {
    let g_lines = split(to_string(gaps), "\\n")
    each g in g_lines {
      let q2 = trim(g)
      if q2 != "" and used < max_searches then {
        let r2 = ExpertTavilySearch(q2, chat_id)
        let used = used + 1.0
        if r2 != "" then { let out = out + "\\n[" + q2 + "]\\n" + r2 + "\\n" }
      }
    }
  }
  // ── круг 3: только /deepexpert (если лимит не исчерпан) ──
  if deep == true and used < max_searches then {
    let deep_sys = "Финальный круг глубокого разбора (до 25 поисков). Что ещё проверить профессионалу мирового уровня: редкие отказы, ценовые аномалии, конкурирующие альтернативы? До 5 запросов, один на строку, без пояснений. Если нечего — пустой ответ."
    let deep_gaps = redact(to_string(TryVal(try call_llm(deep_sys, "Тема: " + query + "\\nУже найдено (выдержки):\\n" + substring(out, 0.0, 6000.0)))), "all")
    if to_string(deep_gaps) != "()" and length(to_string(deep_gaps)) > 10.0 then {
      let d_lines = split(to_string(deep_gaps), "\\n")
      each d in d_lines {
        let q3 = trim(d)
        if q3 != "" and used < max_searches then {
          let r3 = ExpertTavilySearch(q3, chat_id)
          let used = used + 1.0
          if r3 != "" then { let out = out + "\\n[" + q3 + "]\\n" + r3 + "\\n" }
        }
      }
    }
  }
  return out
}

// ── B.5+B.6+B.7: полный конвейер отчёта ────────────────────────────────
pattern ExpertRunReport(query: String, chat_id: String, deep: Bool) -> String {
  let dept = "expert"
  let max_searches = ExpertSearchMax()
  if deep == true then { let max_searches = ExpertDeepSearchMax() }

  // B.1 профессия
  let profession_line = ExpertDetectProfession(query)

  // B.2 шкурка (или черновик)
  let skin_block = ExpertPickSkin(query, profession_line)

  // B.3 план поиска
  let plan = ExpertSearchPlan(query, profession_line, skin_block)

  // B.7 инструменты шкурки auto: живые листинги + остаточная стоимость
  // — в раздел «Цифры» (результаты вставляются в контекст с пометкой)
  let auto_tools = ""
  if contains(lower(profession_line), "авто") or contains(lower(query), "авто") or contains(lower(query), "Toyota") or contains(lower(query), "BMW") or contains(lower(query), "Mercedes") or contains(lower(query), "Volkswagen") or contains(lower(query), "Hyundai") or contains(lower(query), "Kia") then {
    let listings = ExpertAvByListings(query)
    if listings != "" then {
      let auto_tools = auto_tools + "\\n\\n=== Инструменты шкурки: живые объявления av.by (вставить в раздел «Цифры») ===\\n" + listings
    }
    let rv = ExpertResidualValueData(query, chat_id)
    if rv != "" then {
      let auto_tools = auto_tools + "\\n\\n=== Инструменты шкурки: остаточная стоимость (вставить в раздел «Цифры») ===\\n" + rv
    }
  }

  // B.4 поиск кругами (полные тексты результатов до бюджета контекста)
  let live = ExpertSearchCircles(query, plan, max_searches, chat_id, deep)
  let live_section = ""
  if length(live) > 0.0 then {
    let live_section = "\\n\\n=== Live Search (кругами, до " + to_string(to_int(max_searches)) + " поисков) ===\\n" + live + auto_tools
  } else {
    let live_section = "\\n\\n=== Live Search ===\\n(свежих данных живой поиск не дал" + (if contains(auto_tools, "===") then ", но инструменты шкурки дали данные ниже" else " — оценки текущего состояния мира давай только с явной пометкой об отсутствии свежих данных)") + auto_tools
  }

  // B.5 черновик по шаблону EXP-1 (9 разделов)
  let template_md = redact(read_file_or("library/expert_report_template.md", ""), "all")
  if to_string(template_md) == "()" or length(to_string(template_md)) < 100.0 then { let template_md = "" }
  let profile = ReadDeptProfile("expert")
  let corrections = GetCorrections(dept)
  let facts = GetFacts(dept, "12")
  let dialog = GetRecentDialog(chat_id, "10", dept)
  let now_info = YanaNowInfo()
  let draft_sys = "Ты — Эксперт, профессионал мирового уровня. Составь черновик отчёта СТРОГО по шаблону (9 разделов, фиксированный порядок).\\n\\n=== ШАБЛОН ===\\n" + template_md + "\\n\\n=== ПРАВИЛА (профиль, вкратце) ===\\n" + substring(profile, 0.0, 6000.0)
  let draft_user = "Запрос владельца: " + query + "\\n\\nПрофессия: " + profession_line + "\\n\\n" + skin_block + live_section + "\\n\\n=== Консолидированные факты ===\\n" + facts + "\\n\\n=== Recent Dialog ===\\n" + dialog
  let draft = redact(to_string(TryVal(try call_llm(draft_sys, draft_user))), "all")
  if to_string(draft) == "()" then { return "Разбор недоступен: провайдеры модели не ответили (поиск выполнен, результаты сохранены в этом сообщении чата).\\n\\n" + ExpertSourcesFooter(live_section) }
  let reply = to_string(draft)

  // B.6 разбор «конкурирующим профессионалом» — сильная модель из реестра
  let rival = TryVal(try call_python("llm_verifier", "rival_review", json_encode([query, reply, live])))
  let rival_note = ""
  if to_string(rival) != "()" then {
    let rival_parsed = TryVal(try parse_json(to_string(rival)))
    let rival_ok = to_string(json_get(rival_parsed, "ok", "0"))
    if rival_ok == "1" then {
      let notes = to_string(json_get(rival_parsed, "notes", ""))
      if length(notes) > 5.0 then {
        // финальная сборка: черновик + правки конкурирующего профессионала;
        // вычеркнутое не возвращается
        let rival_model = redact(to_string(json_get(rival_parsed, "model", "")), "all")
        let final_sys = "Ты — Эксперт. Твой черновик разобрал конкурирующий профессионал (сильная модель" + (if rival_model != "" then " " + rival_model else "") + "). Примени правки: утверждения без механизма/источника — убрать или дополнить; общие фразы — конкретизировать; пропущенные известные отказы — добавить в «Отрицательные нюансы» по форме. Вычеркнутое НЕ возвращать. Структуру 9 разделов сохранить."
        let final_user = "Черновик:\\n" + reply + "\\n\\n=== Правки конкурирующего профессионала ===\\n" + notes
        let final_r = redact(to_string(TryVal(try call_llm(final_sys, final_user))), "all")
        if to_string(final_r) != "()" and length(to_string(final_r)) > 200.0 then {
          let reply = to_string(final_r)
          let _ = AuditLog("expert_rival_applied", dept, "model=" + rival_model)
        }
      }
    } else {
      // правило при затруднении: сильная модель недоступна — пометка, не тишина
      let rival_note = "\\n\\n---\\n⚠️ Второй проход «конкурирующим профессионалом» не выполнен: " + redact(to_string(json_get(rival_parsed, "note", "сильная модель недоступна")), "all")
    }
  } else {
    let rival_note = "\\n\\n---\\n⚠️ Второй проход «конкурирующим профессионалом» не выполнен: шов rival_review недоступен."
  }

  // Вербификатор: критерий — глубина, механизм, источники негативных нюансов
  if length(query) > 80.0 then {
    let ev_resp = TryVal(try call_python("llm_verifier", "score", json_encode([query, reply, "Depth: Professional-world-level depth? Mechanism: Every nuance has a why? Sources: Negative nuances sourced or marked as practitioner experience?"])))
    let mut ev_score = 0.5
    if to_string(ev_resp) != "()" and contains(to_string(ev_resp), "error") == false then {
      let ev_parsed = TryVal(try parse_json(ev_resp))
      let ev_score = to_float(TryVal(try json_get(ev_parsed, "result", "0.5")))
      let _ = AuditLog("expert_verify_score", dept, "score=" + to_string(ev_score) + " query=" + substring(query, 0.0, 60.0))
    }
    if ev_score < 0.55 then {
      let llm_result2 = redact(to_string(TryVal(try call_llm(draft_sys, draft_user))), "all")
      if to_string(llm_result2) != "()" then {
        let reply2 = to_string(llm_result2)
        let sel_resp = TryVal(try call_python("llm_verifier", "select", json_encode([query, json_encode([reply, reply2]), "Depth: Professional depth? Mechanism: Every nuance has a why? Sources: Negative nuances sourced?"])))
        if to_string(sel_resp) != "()" and contains(to_string(sel_resp), "error") == false then {
          let sel_parsed = TryVal(try parse_json(sel_resp))
          let best_idx = to_int(TryVal(try json_get(sel_parsed, "result", "0")))
          if best_idx == 1 then { let reply = reply2 }
          let _ = AuditLog("expert_bestof2", dept, "original_score=" + to_string(ev_score) + " selected=" + to_string(best_idx))
        }
      }
    }
  }

  // TEAM-2 #481 A.3: консультации коллег — как было
  let enhanced = TeamSecondPass(dept, query, "профессия: " + profession_line, reply)
  if enhanced != "" then { let reply = enhanced }

  // Дисклеймер: медицина/право/финансы — без сокращения глубины
  let t_prof = lower(profession_line)
  if contains(t_prof, "врач") or contains(t_prof, "медиц") or contains(t_prof, "мед.") or contains(t_prof, "медицин") or contains(t_prof, "юрист") or contains(t_prof, "право") or contains(t_prof, "адвокат") or contains(t_prof, "финанс") or contains(t_prof, "аудит") or contains(t_prof, "medical") or contains(t_prof, "legal") or contains(t_prof, "finance") then {
    let reply = reply + "\\n\\n---\\nинформационный разбор, не консультация специалиста"
  }

  let reply = reply + rival_note + ExpertSourcesFooter(live_section) + "\\n\\n(" + to_string(to_int(max_searches)) + " поисков лимит; шкурок-домен: " + (if contains(skin_block, "Шкурка надета") then "надета" else "черновик/нет") + ")"
  let _ = RecordAssistantMessage(chat_id, dept, reply)
  let _ = AuditLog("dept_query", dept, "deep=" + (if deep == true then "1" else "0") + " query: " + substring(query, 0.0, 100.0))
  return reply
}

// Подвал со списком реально использованных источников — построен по
// меткам, которые context уже содержит (не выдумка, не отдельный
// вызов модели, честная проверка того, что реально было подмешано).'''

cut_start = "pattern HandleExpert(query: String, chat_id: String) -> String {"
cut_end = "pattern ExpertSourcesFooter(context: String) -> String {"
i = src.index(cut_start)
j = src.index(cut_end)
src = src[:i] + new_handle + "\n\n" + src[j:]

# ── A: ExpertDetectDeadline + LoadExpertSkills (секции целиком) ─────────
cut("// TIER-BASED SKILL LOADING (like OSP pattern)", "pattern ExpertDetectDeadline")
cut("pattern ExpertDetectDeadline(query: String) -> Bool {", "pattern ExpertAutomotiveKB() -> String {")
# KB+SkillSet+Lookup+Compare: от маркера KB до ResidualValueData (остаётся)
cut("pattern ExpertAutomotiveKB() -> String {", "pattern ExpertResidualValueData(query: String, chat_id: String) -> String {")
# Briefing lifecycle: от паттерна CreateBriefing до TEAM-стаба ExpertBrief
cut("pattern ExpertCreateBriefing(topic: String, depth: String, chat_id: String) -> String {", "// ── TEAM-2 #481 A.1: навык expert/brief")
# BRIEFING LIFECYCLE-заголовок перед CreateBriefing уже вырезан вместе.

# ── BuildExpertContext: шкурка вместо KB/skills, поиск уходит в конвейер ─
old_ctx = '''pattern BuildExpertContext(query: String, chat_id: String) -> String {
  let profile = ReadDeptProfile("expert")
  let skills = LoadExpertSkills(query)
  let corrections = GetCorrections("expert")
  let dialog = GetRecentDialog(chat_id, "10", "expert")
  let facts = GetFacts("expert", "12")
  let memories = YanaRecallMemories(query)
  let now_info = YanaNowInfo()
  let mut auto_kb = ""
  if ExpertIsAutomotiveTopic(query) == true then {
    let auto_kb = ExpertAutomotiveKB()
    // av.by (#336): живые объявления — только на автомобильной теме
    let avby_section = ExpertAvByListings(query)
    if avby_section != "" then {
      let auto_kb = auto_kb + "\\n\\n=== Реальные предложения av.by (живые объявления) ===\\n" + avby_section
    }
  }
  // Фаза 1 — быстрый широкий поиск по самой теме
  let initial = ExpertTavilySearch(query, chat_id)
  // Фаза 2 — модель планирует 2-4 узких под-вопроса на основе фазы 1
  let sub_queries = ExpertPlanSubQueries(query, initial)
  // Фаза 3 — прицельный поиск по каждому под-вопросу
  let targeted = ExpertTargetedSearches(sub_queries, chat_id)
  let live = initial + targeted
  let live_section = ""
  if live != "" then { let live_section = "\\n\\n=== Live Search (двухфазный) ===\\n" + live } else { let live_section = "\\n\\n=== Live Search (двухфазный) ===\\n(свежих данных живой поиск не дал — оценки текущего состояния мира давай только с явной пометкой об отсутствии свежих данных)" }
'''
new_ctx = '''#744 EXP-2: BuildExpertContext больше не главный путь — конвейер
# ExpertRunReport строит контекст сам (шкурка/поиск/шаблон). Паттерн
# сохранён для совместимости TEAM-вызовов: база без поиска и KB.
pattern BuildExpertContext(query: String, chat_id: String) -> String {
  let profile = ReadDeptProfile("expert")
  let corrections = GetCorrections("expert")
  let dialog = GetRecentDialog(chat_id, "10", "expert")
  let facts = GetFacts("expert", "12")
  let memories = YanaRecallMemories(query)
  let now_info = YanaNowInfo()
'''
assert src.count(old_ctx) == 1, "ctx"
src = src.replace(old_ctx, new_ctx, 1)
# хвост BuildExpertContext: убрать skills/auto_kb из сборки
old_tail = '''  let context = profile + "\\n\\n=== Текущая дата и время ===\\n" + now_info + "\\n\\n=== Active Skills ===\\n" + skills + "\\n\\n=== Automotive Knowledge Base ===\\n" + auto_kb + live_section + cross_section + "\\n\\n=== Corrections ===\\n" + corrections + "\\n\\n=== Long-term Memory ===\\n" + memories + "\\n\\n=== Консолидированные факты ===\\n" + facts + "\\n\\n=== Recent Dialog ===\\n" + dialog + TeamAskBlock("expert")'''
new_tail = '''  let context = profile + "\\n\\n=== Текущая дата и время ===\\n" + now_info + cross_section + "\\n\\n=== Corrections ===\\n" + corrections + "\\n\\n=== Long-term Memory ===\\n" + memories + "\\n\\n=== Консолидированные факты ===\\n" + facts + "\\n\\n=== Recent Dialog ===\\n" + dialog + TeamAskBlock("expert")'''
assert src.count(old_tail) == 1, "tail"
src = src.replace(old_tail, new_tail, 1)

# ── Disclaimer: без «встреч» ─────────────────────────────────────────────
old_disc = '''pattern ExpertDisclaimer() -> String {
  return "FOSVED ЭКСПЕРТ — брифинг для подготовки к встрече. Не заменяет собственное суждение владельца."
}'''
new_disc = '''pattern ExpertDisclaimer() -> String {
  return "FOSVED ЭКСПЕРТ — профессиональный разбор. Информационный разбор, не консультация специалиста. Не заменяет собственное суждение владельца."
}'''
assert src.count(old_disc) == 1, "disc"
src = src.replace(old_disc, new_disc, 1)

# ── Заголовок файла ──────────────────────────────────────────────────────
old_head = '''// Fosved Office v2 — Expert Department v2.1 (NATIVE)
// Автопром + сравнительный анализ + графики остаточной стоимости/эксплуатации + брифинг lifecycle
// MEGA-4: 12 Transition Pack skills + automotive domain + comparative engine + chart data
// ENRICHED: 0 CallLLMProxy, 4 native call_llm, disclaimer, 6 hard gates'''
new_head = '''// Fosved Office v2 — Expert Department v3.0 (NATIVE, #744 EXP-2)
// Конвейер: профессия → шкурка (или черновик) → поиск кругами до 12/25 →
// черновик по шаблону 9 разделов → разбор «конкурирующим профессионалом»
// (сильная модель, llm_verifier.rival_review). Гейта дедлайна нет,
// брифингов нет, несуществующие скиллы удалены. Инструменты шкурки auto:
// ExpertAvByListings / ExpertResidualValueData / ExpertOperationCostData /
// ExpertGenerateChart (вызывает конвейер, подкоманд нет).'''
assert src.count(old_head) == 1, "head"
src = src.replace(old_head, new_head, 1)

P.write_text(src, encoding="utf-8")
print("dept/expert.mlog рефакторинг выполнен")
