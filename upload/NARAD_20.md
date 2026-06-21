# НАРЯД №20: Офис как продукт — фабрика клиентских офисов

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** команда `/factory` запускает процесс создания AI-офиса для клиента

---

## Концепция

Fosved Office — не только персональный штаб, но и платформа. Заказчик приходит → офис создаёт для него AI-офис: опрос → профили отделов → кастомизация → деплой → передача.

Весь процесс управляется из Telegram через Яну.

---

## Реализация

### 1. Таблица заказов

```mlog
db_execute("CREATE TABLE IF NOT EXISTS factory_orders (
  id TEXT PRIMARY KEY,
  client_name TEXT NOT NULL,
  status TEXT DEFAULT 'intake',
  requirements TEXT,
  departments TEXT,
  branding TEXT,
  llm_config TEXT,
  repo_url TEXT,
  render_url TEXT,
  created_at REAL,
  completed_at REAL
)")
```

Статусы: `intake` → `design` → `building` → `testing` → `deployed` → `delivered`

### 2. Команда `/factory` — начать заказ

```mlog
match text {
  "/factory" then {
    let order_id = "order-" + to_string(to_int(now()))
    let _ = query("INSERT INTO factory_orders (id, client_name, status, created_at) VALUES ($1, '', 'intake', $2)",
      [order_id, to_string(now())])

    kv_set("active_order", order_id)
    kv_set("order_step_" + order_id, "name")

    send_message(chat_id, "Zapuskayuproizvodstvo novogo ofisa.\n\nID zakaza: " + order_id + "\n\nShag 1/7: Kak zovut klienta (ili nazvanie kompanii)?")
    let _ = AuditLog("factory_start", "owner", "", order_id, "intake")
    return respond("200 ok")
  }
}
```

### 3. Пошаговый опрос (7 шагов)

Яна ведёт интервью — каждый шаг сохраняется, переход к следующему:

```mlog
pattern HandleFactoryStep(order_id: String, step: String, answer: String, chat_id: String) -> String {
  match step {
    "name" then {
      let _ = query("UPDATE factory_orders SET client_name = $1 WHERE id = $2", [answer, order_id])
      kv_set("order_step_" + order_id, "tasks")
      send_message(chat_id, "Shag 2/7: Kakiye zadachi budet reshat' ofis klienta? (opisanie v svobodnoj forme)")
      return "ok"
    }
    "tasks" then {
      let _ = query("UPDATE factory_orders SET requirements = $1 WHERE id = $2", [answer, order_id])
      kv_set("order_step_" + order_id, "departments")

      // LLM предлагает набор отделов на основе задач
      let suggest_prompt = "Na osnove zadach klienta predlozhi nabor otdelov dlya AI-ofisa. Dostupnye shablony otdelov: OSP (analitika), LZ (monitoring), Expert (brifingi), Marketing, Finance, Legal, Dev, Design, QA, Visual, Engineering, Kaval'nya.\n\nOtveti v formate: slug1, slug2, slug3\nI kratko pochemu kazhdyj nuzhen."
      let suggestion = call_llm(suggest_prompt, "Zadachi klienta: " + answer)

      send_message(chat_id, "Shag 3/7: Kaval'nya predlagayet otdely:\n\n" + suggestion + "\n\nSoglasny? Ili ukazhite svoi (slugi cherez zapyatuyu): osp, finance, legal, ...")
      return "ok"
    }
    "departments" then {
      let _ = query("UPDATE factory_orders SET departments = $1 WHERE id = $2", [answer, order_id])
      kv_set("order_step_" + order_id, "branding")
      send_message(chat_id, "Shag 4/7: Brending:\n- Nazvanie ofisa?\n- Osnovnoj yazyk (ru/en)?\n- Stil' obshcheniya (formal'nyj / druzhestvenny / tekhnichnye)?")
      return "ok"
    }
    "branding" then {
      let _ = query("UPDATE factory_orders SET branding = $1 WHERE id = $2", [answer, order_id])
      kv_set("order_step_" + order_id, "llm")
      send_message(chat_id, "Shag 5/7: Kakoj LLM-provajder budet ispol'zovat' klient?\n- zai (GLM 4.6)\n- deepseek\n- groq\n- grok\n- anthropic\n- openai\n\nMozhno neskol'ko cherez zapyatuyu. Klient predostavit svoi klyuchi.")
      return "ok"
    }
    "llm" then {
      let _ = query("UPDATE factory_orders SET llm_config = $1 WHERE id = $2", [answer, order_id])
      kv_set("order_step_" + order_id, "confirm")

      // Показать сводку
      let name = to_string(query("SELECT client_name FROM factory_orders WHERE id = $1", [order_id]))
      let reqs = to_string(query("SELECT requirements FROM factory_orders WHERE id = $1", [order_id]))
      let depts = to_string(query("SELECT departments FROM factory_orders WHERE id = $1", [order_id]))
      let brand = to_string(query("SELECT branding FROM factory_orders WHERE id = $1", [order_id]))

      let summary = "Shag 6/7: SVODKA ZAKAZA\n\n"
        + "Klient: " + name + "\n"
        + "Zadachi: " + reqs + "\n"
        + "Otdely: " + depts + "\n"
        + "Brending: " + brand + "\n"
        + "LLM: " + answer + "\n\n"
        + "Vsyo verno? (da / net / izmenit' shag N)"

      send_message(chat_id, summary)
      return "ok"
    }
    "confirm" then {
      if contains(answer, "da") then {
        let _ = query("UPDATE factory_orders SET status = 'design' WHERE id = $1", [order_id])
        kv_set("order_step_" + order_id, "building")
        send_message(chat_id, "Shag 7/7: Zapuskayu proizvodstvo!\n\n1. Kaval'nya sozdayot profili otdelov...\n2. Design podbirayetcveta...\n3. Dev generiruyet proekt...\n\nEto zaymet 2-3 minuty. Soobshchu kogda budet gotovo.")

        let _ = BuildClientOffice(order_id, chat_id)
        return "ok"
      } else {
        send_message(chat_id, "Chto izmenit'? Ukazhite shag (1-5) ili opishite.")
        return "ok"
      }
    }
    else { return "unknown step" }
  }
}
```

### 4. Роутинг ответов в factory flow

В основном webhook handler, перед обычной маршрутизацией:

```mlog
    // Проверяем активный заказ
    let active_order = kv_get("active_order")
    if len(active_order) > 5 then {
      let step = kv_get("order_step_" + active_order)
      if len(step) > 1 then {
        if step != "building" then {
          let _ = HandleFactoryStep(active_order, step, text, chat_id)
          return respond("200 ok")
        }
      }
    }
```

### 5. Генерация клиентского офиса

```mlog
pattern BuildClientOffice(order_id: String, chat_id: String) -> String {
  let name = to_string(query("SELECT client_name FROM factory_orders WHERE id = $1", [order_id]))
  let reqs = to_string(query("SELECT requirements FROM factory_orders WHERE id = $1", [order_id]))
  let depts_str = to_string(query("SELECT departments FROM factory_orders WHERE id = $1", [order_id]))
  let brand = to_string(query("SELECT branding FROM factory_orders WHERE id = $1", [order_id]))
  let llm_config = to_string(query("SELECT llm_config FROM factory_orders WHERE id = $1", [order_id]))

  // 1. Кавальня генерирует профили отделов
  send_message(chat_id, "[1/4] Kaval'nya sozdayot profili otdelov...")
  let kavalnya_profile = read_file("library/kavalnya.md")
  let profiles_prompt = "Sozdaj kompaktnye profili (20-30 strok kazhdyj) dlya otdelov: " + depts_str + "\n\nKlient: " + name + "\nZadachi: " + reqs + "\nBrending: " + brand + "\n\nDlya kazhdogo otdela:\n- Rol' i zadachi\n- Zhyostkie pravila (5-8)\n- Format otveta\n- Ton obshcheniya\n\nFormat: DEPT:slug\nPROFILE:\n...tekst...\nEND_DEPT"
  let profiles = call_llm(kavalnya_profile + "\n\n" + profiles_prompt, "Profili dlya " + name)

  // 2. Design подбирает цвета
  send_message(chat_id, "[2/4] Design podbirayetcveta...")
  let design_profile = read_file("library/design.md")
  let colors_prompt = "Podberi unikal'nye gradienty dlya otdelov: " + depts_str + "\nBrending: " + brand + "\n\nFormat: slug:grad_start,grad_end,accent\nPrimer: osp:#b91c1c,#7f1d1d,#dc2626"
  let colors = call_llm(design_profile + "\n\n" + colors_prompt, "Cveta dlya " + name)

  // 3. Dev генерирует проект
  send_message(chat_id, "[3/4] Dev generiruyet proyekt...")
  let dev_profile = read_file("library/dev.md")
  let project_prompt = "Sgeneriruuj strukturu proyekta klientskogo AI-ofisa na Metalogos.\n\nKlient: " + name + "\nOtdely: " + depts_str + "\nLLM: " + llm_config + "\n\nNuzhny fayly:\n1. app.mlog (server + webhook + marshrutizaciya)\n2. library/*.md (profili otdelov)\n3. Dockerfile\n4. README.md s instrukciyami\n5. config/ (model, provider)\n\nFormat: FILE:path\nCONTENT:\n...soderzhimoye...\nEND_FILE"
  let project = call_llm(dev_profile + "\n\n" + project_prompt, "Proyekt dlya " + name)

  // 4. Сохранить результат
  send_message(chat_id, "[4/4] Sobirayurezul'tat...")

  // Сохранить сгенерированный проект в БД
  let _ = query("INSERT INTO miniapp_responses (id, dept, title, query, raw_text, html) VALUES ($1, 'factory', $2, $3, $4, '')",
    [order_id, "Ofis dlya " + name, reqs, project])

  let _ = query("UPDATE factory_orders SET status = 'testing' WHERE id = $1", [order_id])

  // Очистить активный заказ
  kv_delete("active_order")
  kv_delete("order_step_" + order_id)

  // Отчёт владельцу
  let report = "Ofis dlya " + name + " sgenerirovon!\n\n"
    + "Otdely: " + depts_str + "\n"
    + "LLM: " + llm_config + "\n\n"
    + "Sleduyushchiye shagi:\n"
    + "1. /factory_review " + order_id + " — proverit' profili\n"
    + "2. /factory_deploy " + order_id + " — zadiployit' na Render\n"
    + "3. /factory_deliver " + order_id + " — peredat' klientu"
  send_message(chat_id, report)

  let _ = AuditLog("factory_built", "system", "factory", order_id, "testing")
  return "ok"
}
```

### 6. Review сгенерированного офиса

```mlog
match text {
  starts_with "/factory_review " then {
    let order_id = substring(text, 16, len(text))
    let project = to_string(query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [order_id]))
    if len(project) > 10 then {
      let _ = SendReport(project, "factory", "Review: " + order_id, 2.0, chat_id)
    } else {
      send_message(chat_id, "Zakaz " + order_id + " ne najden")
    }
    return respond("200 ok")
  }
}
```

### 7. Deploy клиентского офиса

```mlog
match text {
  starts_with "/factory_deploy " then {
    let order_id = substring(text, 16, len(text))

    send_message(chat_id, "Deploy klientskogo ofisa...\n\n1. Sozdayu GitHub repo...\n2. Zalivayufayly...\n3. Sozdayu Render service...\n\nEto mozhet zanyat' neskol'ko minut.")

    // Создать GitHub repo через API
    let github_token = env("GITHUB_TOKEN")
    let client_name = to_string(query("SELECT client_name FROM factory_orders WHERE id = $1", [order_id]))
    let repo_name = replace(lower(client_name), " ", "-") + "-office"

    let create_body = json_encode({
      name: repo_name,
      description: "AI Office for " + client_name + " — powered by Fosved/Metalogos",
      private: true
    })
    let headers = { "Authorization": "Bearer " + github_token, "Accept": "application/vnd.github.v3+json" }
    let create_result = http_post("https://api.github.com/user/repos", json_encode(create_body), "application/json", headers)

    let parsed = parse_json(create_result)
    let repo_url = json_get(parsed, "html_url", "")

    let _ = query("UPDATE factory_orders SET repo_url = $1, status = 'deployed' WHERE id = $2",
      [to_string(repo_url), order_id])

    send_message(chat_id, "Repo sozdano: " + to_string(repo_url) + "\n\nDlya zaversheniyadeploya:\n1. Dobav'te fayly v repo\n2. Sozdajte Render Web Service\n3. Dobav'te env vars klienta\n\n/factory_deliver " + order_id + " — kogda vsyo gotovo")

    let _ = AuditLog("factory_deploy", "system", "factory", order_id + " -> " + to_string(repo_url), "deployed")
    return respond("200 ok")
  }
}
```

### 8. Передача клиенту

```mlog
match text {
  starts_with "/factory_deliver " then {
    let order_id = substring(text, 17, len(text))
    let _ = query("UPDATE factory_orders SET status = 'delivered', completed_at = $1 WHERE id = $2",
      [to_string(now()), order_id])

    let name = to_string(query("SELECT client_name FROM factory_orders WHERE id = $1", [order_id]))
    let repo = to_string(query("SELECT repo_url FROM factory_orders WHERE id = $1", [order_id]))

    send_message(chat_id, "Ofis peredan klientu " + name + "!\n\nRepo: " + repo + "\nStatus: delivered")

    // Публикация в архивный канал
    let channel_id = env("TELEGRAM_ARCHIVE_CHANNEL_ID")
    send_message(channel_id, "[FACTORY] Ofis dlya " + name + " dostavlen\nRepo: " + repo + "\n#Factory #delivered")

    let _ = AuditLog("factory_deliver", "owner", "factory", order_id, "delivered")
    return respond("200 ok")
  }
}
```

### 9. Список заказов

```mlog
match text {
  "/factory_list" then {
    let orders = to_string(query("SELECT id, client_name, status, created_at FROM factory_orders ORDER BY created_at DESC LIMIT 10", []))
    if len(orders) > 2 then {
      send_message(chat_id, "Zakazy:\n" + orders)
    } else {
      send_message(chat_id, "Net zakazov. /factory — sozdat' novyj")
    }
    return respond("200 ok")
  }
}
```

---

## Базовый шаблон (что переиспользуется)

Каждый клиентский офис наследует:
- Runtime Metalogos (bin/mlog)
- Базовую архитектуру (server, webhook, memory, context manager)
- Mini App framework (template, CSS, action bar)
- Lockdown механизм
- Audit log

Кастомизируется:
- Набор отделов (library/*.md)
- Цвета (DeptColors)
- Маршрутизация (keywords)
- LLM provider/model (config/)
- Название и тон ассистента
- Язык (ru/en)

---

## Команды

| Команда | Действие |
|---|---|
| `/factory` | Начать новый заказ (7-шаговый опрос) |
| `/factory_review <id>` | Просмотреть сгенерированный проект |
| `/factory_deploy <id>` | Создать repo + deploy |
| `/factory_deliver <id>` | Пометить как доставленный |
| `/factory_list` | Список всех заказов |

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /factory ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/factory","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T2: ответ на шаг 1 (имя) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"TestCompany","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T3: /factory_list ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/factory_list","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Office factory: /factory, 7-step intake, auto-generate profiles, deploy, deliver"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №20

1. Таблица factory_orders: [✅/❌]
2. /factory (7-шаговый опрос): [✅/❌]
3. HandleFactoryStep: [✅/❌]
4. BuildClientOffice (LLM-генерация): [✅/❌]
5. /factory_review: [✅/❌]
6. /factory_deploy (GitHub API): [✅/❌]
7. /factory_deliver: [✅/❌]
8. /factory_list: [✅/❌]
9. Роутинг factory flow в webhook: [✅/❌]
10. Audit log интеграция: [✅/❌]
11. T1-T3 проверки: [✅/❌]
12. git push: [✅/❌] [хэш]
13. Проблемы: [если есть]
```
