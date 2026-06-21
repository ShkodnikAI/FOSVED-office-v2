# НАРЯД №22: ЛЗ — глубокое сканирование интернета

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** ЛЗ сканирует веб, соцсети, Telegram-каналы, YouTube, научные базы, даркнет по запросу

---

## Концепция

Сейчас ЛЗ отвечает из знаний LLM — то есть из прошлого. Нужно чтобы ЛЗ **реально сканировал** интернет в реальном времени и собирал свежие данные из множества источников.

---

## Источники (9 категорий)

| # | Источник | API/метод | Что ищем |
|---|---|---|---|
| 1 | Веб (общий) | Google Custom Search API / SerpAPI | Новости, статьи, блоги |
| 2 | Telegram-каналы | Telegram Bot API + подписка на каналы | Инсайды, утечки, оперативка |
| 3 | YouTube | YouTube Data API v3 | Видео, интервью, разборы |
| 4 | Reddit | Reddit API (OAuth2) | Обсуждения, тренды, мнения |
| 5 | Научные базы | Semantic Scholar API / arXiv API | Статьи, препринты, исследования |
| 6 | Twitter/X | через Grok API или SerpAPI | Тренды, заявления, реакции |
| 7 | TikTok/Instagram/Threads | SerpAPI Social / RapidAPI | Вирусный контент, тренды |
| 8 | GitHub | GitHub API | Репозитории, issues, releases |
| 9 | Даркнет | Ahmia API / OnionSearch | Утечки, торговля данными, угрозы |

---

## Реализация

### 1. Новые builtins в Metalogos

**`web_search(query, num_results)` → String (JSON)**

Поиск через SerpAPI (агрегатор, один ключ — все поисковики):

```rust
fn builtin_web_search(args: Vec<Value>) -> Result<Value, String> {
    let query = args[0].as_str()?;
    let num = if args.len() > 1 { args[1].as_f64()? as i32 } else { 10 };
    let api_key = std::env::var("SERPAPI_KEY").unwrap_or_default();

    let client = reqwest::blocking::Client::new();
    let url = format!(
        "https://serpapi.com/search.json?q={}&num={}&api_key={}&hl=ru",
        urlencoding::encode(query), num, api_key
    );
    let resp = client.get(&url).timeout(Duration::from_secs(15))
        .send().map_err(|e| e.to_string())?;
    let text = resp.text().map_err(|e| e.to_string())?;
    Ok(Value::Str(text))
}
```

Если SerpAPI не подходит — альтернативы: Google Custom Search API, Brave Search API (бесплатный tier), DuckDuckGo (без ключа через html-парсинг).

**Или проще:** использовать `http_get` + бесплатные API. Тогда новых builtins не нужно.

### 2. Pattern ScanWeb — общий веб-поиск

```mlog
pattern ScanWeb(query: String) -> String {
  let serpapi_key = env("SERPAPI_KEY")
  let encoded = replace(query, " ", "+")
  let url = "https://serpapi.com/search.json?q=" + encoded + "&num=10&api_key=" + serpapi_key + "&hl=ru"
  let result = http_get(url)
  let parsed = parse_json(result)

  // Извлечь заголовки и ссылки
  let snippets = ""
  let i = 0.0
  while i < 10.0 {
    let title = json_get(parsed, "organic_results." + to_string(to_int(i)) + ".title", "")
    let link = json_get(parsed, "organic_results." + to_string(to_int(i)) + ".link", "")
    let snippet = json_get(parsed, "organic_results." + to_string(to_int(i)) + ".snippet", "")
    if len(title) > 2 then {
      let snippets = snippets + to_string(to_int(i) + 1.0) + ". " + title + "\n" + link + "\n" + snippet + "\n\n"
    }
    let i = i + 1.0
  }
  return snippets
}
```

### 3. Pattern ScanYouTube

```mlog
pattern ScanYouTube(query: String) -> String {
  let yt_key = env("YOUTUBE_API_KEY")
  let encoded = replace(query, " ", "+")
  let url = "https://www.googleapis.com/youtube/v3/search?part=snippet&q=" + encoded + "&maxResults=5&type=video&relevanceLanguage=ru&key=" + yt_key
  let result = http_get(url)
  let parsed = parse_json(result)

  let videos = ""
  let i = 0.0
  while i < 5.0 {
    let title = json_get(parsed, "items." + to_string(to_int(i)) + ".snippet.title", "")
    let video_id = json_get(parsed, "items." + to_string(to_int(i)) + ".id.videoId", "")
    let channel = json_get(parsed, "items." + to_string(to_int(i)) + ".snippet.channelTitle", "")
    let published = json_get(parsed, "items." + to_string(to_int(i)) + ".snippet.publishedAt", "")
    if len(title) > 2 then {
      let videos = videos + title + "\n" + channel + " · " + published + "\nhttps://youtube.com/watch?v=" + video_id + "\n\n"
    }
    let i = i + 1.0
  }
  return videos
}
```

### 4. Pattern ScanReddit

```mlog
pattern ScanReddit(query: String) -> String {
  let encoded = replace(query, " ", "+")
  let url = "https://www.reddit.com/search.json?q=" + encoded + "&sort=new&limit=10"
  let headers = { "User-Agent": "FosvedOffice/1.0" }
  let result = http_get(url, headers)
  let parsed = parse_json(result)

  let posts = ""
  let i = 0.0
  while i < 10.0 {
    let title = json_get(parsed, "data.children." + to_string(to_int(i)) + ".data.title", "")
    let subreddit = json_get(parsed, "data.children." + to_string(to_int(i)) + ".data.subreddit", "")
    let score = json_get(parsed, "data.children." + to_string(to_int(i)) + ".data.score", "0")
    let permalink = json_get(parsed, "data.children." + to_string(to_int(i)) + ".data.permalink", "")
    if len(title) > 2 then {
      let posts = posts + title + "\nr/" + subreddit + " · score:" + to_string(score) + "\nhttps://reddit.com" + permalink + "\n\n"
    }
    let i = i + 1.0
  }
  return posts
}
```

### 5. Pattern ScanScience — научные статьи

```mlog
pattern ScanScience(query: String) -> String {
  let encoded = replace(query, " ", "+")

  // Semantic Scholar (бесплатный, без ключа)
  let url = "https://api.semanticscholar.org/graph/v1/paper/search?query=" + encoded + "&limit=5&fields=title,authors,year,abstract,url"
  let result = http_get(url)
  let parsed = parse_json(result)

  let papers = ""
  let i = 0.0
  while i < 5.0 {
    let title = json_get(parsed, "data." + to_string(to_int(i)) + ".title", "")
    let year = json_get(parsed, "data." + to_string(to_int(i)) + ".year", "")
    let paper_url = json_get(parsed, "data." + to_string(to_int(i)) + ".url", "")
    let abstract_text = json_get(parsed, "data." + to_string(to_int(i)) + ".abstract", "")
    if len(title) > 2 then {
      let papers = papers + title + " (" + to_string(year) + ")\n" + paper_url + "\n" + substring(abstract_text, 0, 200) + "\n\n"
    }
    let i = i + 1.0
  }
  return papers
}
```

### 6. Pattern ScanGitHub

```mlog
pattern ScanGitHub(query: String) -> String {
  let encoded = replace(query, " ", "+")
  let github_token = env("GITHUB_TOKEN")
  let headers = { "Authorization": "Bearer " + github_token, "Accept": "application/vnd.github.v3+json" }
  let url = "https://api.github.com/search/repositories?q=" + encoded + "&sort=updated&per_page=5"
  let result = http_get(url, headers)
  let parsed = parse_json(result)

  let repos = ""
  let i = 0.0
  while i < 5.0 {
    let name = json_get(parsed, "items." + to_string(to_int(i)) + ".full_name", "")
    let desc = json_get(parsed, "items." + to_string(to_int(i)) + ".description", "")
    let stars = json_get(parsed, "items." + to_string(to_int(i)) + ".stargazers_count", "0")
    let repo_url = json_get(parsed, "items." + to_string(to_int(i)) + ".html_url", "")
    if len(name) > 2 then {
      let repos = repos + name + " (" + to_string(stars) + " stars)\n" + desc + "\n" + repo_url + "\n\n"
    }
    let i = i + 1.0
  }
  return repos
}
```

### 7. Pattern ScanTelegram — мониторинг каналов

Telegram не имеет API поиска по каналам. Подход: бот подписан на список каналов, новые посты обрабатываются:

```mlog
// Таблица отслеживаемых каналов
db_execute("CREATE TABLE IF NOT EXISTS lz_telegram_channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  channel_name TEXT,
  category TEXT DEFAULT 'general',
  added_at REAL
)")

// Таблица собранных постов
db_execute("CREATE TABLE IF NOT EXISTS lz_telegram_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  channel_name TEXT,
  text TEXT,
  date REAL,
  scanned_at REAL
)")
```

Команда добавления канала:
```mlog
match text {
  starts_with "/lz_channel add " then {
    let args = substring(text, 16, len(text))
    let _ = query("INSERT INTO lz_telegram_channels (channel_id, channel_name, added_at) VALUES ($1, $1, $2)", [args, to_string(now())])
    send_message(chat_id, "Kanal " + args + " dobavlen v monitoring LZ")
    return respond("200 ok")
  }
  "/lz_channels" then {
    let channels = to_string(query("SELECT channel_name, category FROM lz_telegram_channels", []))
    send_message(chat_id, "Kanaly LZ:\n" + channels)
    return respond("200 ok")
  }
}
```

Для чтения постов из каналов — бот должен быть администратором канала, или использовать Telegram channel forwarding. Практичнее: владелец пересылает интересный пост боту, ЛЗ индексирует:

```mlog
// В webhook, если сообщение переслано из канала
let has_forward = has_field(data, "message.forward_from_chat")
if has_forward == 1.0 then {
  let fwd_chat_title = json_get(data, "message.forward_from_chat.title", "unknown")
  let fwd_chat_id = to_string(json_get(data, "message.forward_from_chat.id", "0"))
  let fwd_text = json_get(data, "message.text", "")

  let _ = query("INSERT INTO lz_telegram_posts (channel_id, channel_name, text, date, scanned_at) VALUES ($1, $2, $3, $4, $5)",
    [fwd_chat_id, fwd_chat_title, fwd_text, to_string(now()), to_string(now())])

  send_message(chat_id, "LZ: post iz " + fwd_chat_title + " proindeksirovan")
  return respond("200 ok")
}
```

### 8. Pattern ScanSocial — TikTok/Instagram/Threads

Через SerpAPI Social Search (один ключ покрывает всё):

```mlog
pattern ScanSocial(query: String, platform: String) -> String {
  let serpapi_key = env("SERPAPI_KEY")
  let encoded = replace(query, " ", "+")

  let engine = ""
  match platform {
    "tiktok" then { let engine = "google" }
    "instagram" then { let engine = "google" }
    "threads" then { let engine = "google" }
    else { let engine = "google" }
  }

  // Поиск через Google с фильтром по сайту
  let site_filter = ""
  match platform {
    "tiktok" then { let site_filter = "+site:tiktok.com" }
    "instagram" then { let site_filter = "+site:instagram.com" }
    "threads" then { let site_filter = "+site:threads.net" }
    else { let site_filter = "" }
  }

  let url = "https://serpapi.com/search.json?q=" + encoded + site_filter + "&num=5&api_key=" + serpapi_key
  let result = http_get(url)
  let parsed = parse_json(result)

  let posts = ""
  let i = 0.0
  while i < 5.0 {
    let title = json_get(parsed, "organic_results." + to_string(to_int(i)) + ".title", "")
    let link = json_get(parsed, "organic_results." + to_string(to_int(i)) + ".link", "")
    let snippet = json_get(parsed, "organic_results." + to_string(to_int(i)) + ".snippet", "")
    if len(title) > 2 then {
      let posts = posts + "[" + platform + "] " + title + "\n" + link + "\n" + snippet + "\n\n"
    }
    let i = i + 1.0
  }
  return posts
}
```

### 9. Pattern ScanDarknet

Через Ahmia (поисковик .onion, доступен из clearnet):

```mlog
pattern ScanDarknet(query: String) -> String {
  let encoded = replace(query, " ", "+")
  let url = "https://ahmia.fi/search/?q=" + encoded
  let result = http_get(url)
  // Ahmia возвращает HTML — нужен парсинг
  // Упрощённый вариант: искать через SerpAPI с фильтром
  let serpapi_key = env("SERPAPI_KEY")
  let url2 = "https://serpapi.com/search.json?q=" + encoded + "+site:onion&num=5&api_key=" + serpapi_key
  let result2 = http_get(url2)
  return result2
}
```

**Реальный даркнет-мониторинг** требует Tor + специализированные краулеры. Для MVP: поиск по Ahmia + Google индекс .onion. Полноценный — через внешний сервис (IntelX, DarkOwl API) на фазе масштабирования.

### 10. Главный pattern — DeepScan

Объединяет все источники:

```mlog
pattern DeepScan(query: String, sources: String) -> String {
  let results = ""

  if contains(sources, "web") then {
    let web = ScanWeb(query)
    let results = results + "=== WEB ===\n" + web + "\n"
  }
  if contains(sources, "youtube") then {
    let yt = ScanYouTube(query)
    let results = results + "=== YOUTUBE ===\n" + yt + "\n"
  }
  if contains(sources, "reddit") then {
    let rd = ScanReddit(query)
    let results = results + "=== REDDIT ===\n" + rd + "\n"
  }
  if contains(sources, "science") then {
    let sc = ScanScience(query)
    let results = results + "=== SCIENCE ===\n" + sc + "\n"
  }
  if contains(sources, "github") then {
    let gh = ScanGitHub(query)
    let results = results + "=== GITHUB ===\n" + gh + "\n"
  }
  if contains(sources, "tiktok") then {
    let tt = ScanSocial(query, "tiktok")
    let results = results + "=== TIKTOK ===\n" + tt + "\n"
  }
  if contains(sources, "instagram") then {
    let ig = ScanSocial(query, "instagram")
    let results = results + "=== INSTAGRAM ===\n" + ig + "\n"
  }
  if contains(sources, "threads") then {
    let th = ScanSocial(query, "threads")
    let results = results + "=== THREADS ===\n" + th + "\n"
  }
  if contains(sources, "telegram") then {
    let tg_posts = to_string(query("SELECT channel_name, text FROM lz_telegram_posts WHERE text LIKE '%' || $1 || '%' ORDER BY date DESC LIMIT 10", [query]))
    let results = results + "=== TELEGRAM (indexed) ===\n" + tg_posts + "\n"
  }
  if contains(sources, "darknet") then {
    let dn = ScanDarknet(query)
    let results = results + "=== DARKNET ===\n" + dn + "\n"
  }

  return results
}
```

### 11. Обновить LZ dispatcher

```mlog
// В lz.mlog, обработка /lz
let query = if len(text) > 4 then substring(text, 4, len(text)) else "tekhnologicheskie trendy"

// Определить источники
let sources = "web,youtube,reddit,science,github"
if contains(query, "social") then { let sources = sources + ",tiktok,instagram,threads" }
if contains(query, "darknet") then { let sources = sources + ",darknet" }
if contains(query, "telegram") then { let sources = sources + ",telegram" }
if contains(query, "all") then { let sources = "web,youtube,reddit,science,github,tiktok,instagram,threads,telegram,darknet" }

// Сканирование
send_message(chat_id, "LZ skaniruyet: " + sources + "...")
let scan_results = DeepScan(query, sources)

// LLM анализирует собранное
let lz_profile = read_file("library/lz.md")
let analysis_prompt = lz_profile + "\n\nProanalyziruj sobrannye dannye. Vydelikovnye trendy, signaly, anomalii. Ispol'zuj markery [FAKT], [INTERPRETACIYA], [SPEKULYACIYA]."
let analysis = TrackedLLM("lz", "dept", analysis_prompt, "Zapros: " + query + "\n\nSobrannye dannye:\n" + scan_results)

let _ = SendReport(analysis, "lz", query, 3.0, chat_id)
```

### 12. Команды ЛЗ

```
/lz <запрос>                     → скан web+youtube+reddit+science+github
/lz social <запрос>              → + tiktok, instagram, threads
/lz all <запрос>                 → все 9 источников
/lz darknet <запрос>             → + даркнет
/lz telegram <запрос>            → + индексированные Telegram-посты
/lz_channel add <channel>        → добавить канал в мониторинг
/lz_channels                     → список каналов
/lz_monitor <запрос>             → добавить тему в постоянный мониторинг
```

### 13. Постоянный мониторинг (через scheduler)

```mlog
db_execute("CREATE TABLE IF NOT EXISTS lz_monitors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  sources TEXT DEFAULT 'web,youtube,reddit',
  frequency TEXT DEFAULT 'daily',
  last_scan REAL,
  created_at REAL
)")

match text {
  starts_with "/lz_monitor " then {
    let monitor_query = substring(text, 12, len(text))
    let _ = query("INSERT INTO lz_monitors (query, sources, frequency, created_at) VALUES ($1, 'web,youtube,reddit,science', 'daily', $2)",
      [monitor_query, to_string(now())])
    send_message(chat_id, "LZ: tema '" + monitor_query + "' na ezhrednevnom monitoringe")
    return respond("200 ok")
  }
}
```

В `/cron/morning` добавить:
```mlog
  let _ = LZDailyMonitoring()
```

```mlog
pattern LZDailyMonitoring() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")
  let monitors = to_string(query("SELECT id, query, sources FROM lz_monitors WHERE frequency = 'daily'", []))

  // Для каждой темы — быстрый скан
  // Сравнить с предыдущим сканом — найти новое
  // Если есть значимые находки — alert владельцу

  let _ = AuditLog("lz_monitoring", "scheduler", "lz", "daily scan", "ok")
  return "ok"
}
```

---

## Переменные окружения

```
SERPAPI_KEY=...              # SerpAPI (web + social search)
YOUTUBE_API_KEY=...          # YouTube Data API v3
```

Reddit и Semantic Scholar — без ключа (бесплатные).
GitHub — уже есть GITHUB_TOKEN.

---

## Локальная проверка

```bash
export SERPAPI_KEY=fake
export YOUTUBE_API_KEY=fake
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /lz AI trendy ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/lz AI trends 2026","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T2: /lz_channel add ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/lz_channel add @test_channel","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T3: /lz_monitor ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/lz_monitor quantum computing breakthroughs","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "LZ deep scan: 9 sources (web, YouTube, Reddit, science, GitHub, TikTok, Instagram, Threads, darknet), monitoring, telegram indexing"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №22

1. ScanWeb (SerpAPI/Google): [✅/❌]
2. ScanYouTube: [✅/❌]
3. ScanReddit: [✅/❌]
4. ScanScience (Semantic Scholar): [✅/❌]
5. ScanGitHub: [✅/❌]
6. ScanSocial (TikTok/Instagram/Threads): [✅/❌]
7. ScanDarknet (Ahmia): [✅/❌]
8. ScanTelegram (индексация пересланных): [✅/❌]
9. DeepScan (агрегатор): [✅/❌]
10. /lz с real-time данными: [✅/❌]
11. /lz_channel, /lz_channels: [✅/❌]
12. /lz_monitor + daily cron: [✅/❌]
13. LLM-анализ собранного: [✅/❌]
14. T1-T3 проверки: [✅/❌]
15. git push: [✅/❌] [хэш]
16. Проблемы: [если есть]
```
