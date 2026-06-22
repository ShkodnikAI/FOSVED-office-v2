# НАРЯД №11 (v2): Голос Яны — STT + TTS

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2 + Metalogos-
**Справочник:** METALOGOS_REFERENCE.md (v0.4.0+)
**Результат:** Яна принимает голосовые и отвечает голосом

---

## Часть 1: STT — приём голосовых

### Как работает

1. Владелец отправляет голосовое → Telegram шлёт `message.voice.file_id`
2. Бот скачивает файл через Telegram getFile API
3. Отправляет в Whisper API → получает текст
4. Обрабатывает текст как обычный запрос

### Новые builtins (добавить в Metalogos)

**`whisper_transcribe(file_id, bot_token, whisper_key, provider)`** → String

Единый builtin: скачивает голосовое из Telegram + отправляет в Whisper. Провайдеры: `"openai"` или `"groq"` (бесплатный).

```rust
fn builtin_whisper_transcribe(args: Vec<Value>) -> Result<Value, String> {
    let file_id = args[0].as_str()?;
    let bot_token = args[1].as_str()?;
    let whisper_key = args[2].as_str()?;
    let provider = if args.len() > 3 { args[3].as_str()? } else { "openai" };

    let client = reqwest::blocking::Client::new();

    // 1. Получить URL файла из Telegram
    let get_file_url = format!("https://api.telegram.org/bot{}/getFile?file_id={}", bot_token, file_id);
    let resp = client.get(&get_file_url).timeout(Duration::from_secs(10))
        .send().map_err(|e| e.to_string())?;
    let parsed: serde_json::Value = serde_json::from_str(&resp.text().map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    let file_path = parsed["result"]["file_path"].as_str().unwrap_or("");
    let download_url = format!("https://api.telegram.org/file/bot{}/{}", bot_token, file_path);

    // 2. Скачать аудио
    let audio = client.get(&download_url).timeout(Duration::from_secs(30))
        .send().map_err(|e| e.to_string())?
        .bytes().map_err(|e| e.to_string())?;

    // 3. Отправить в Whisper
    let whisper_url = match provider {
        "groq" => "https://api.groq.com/openai/v1/audio/transcriptions",
        _ => "https://api.openai.com/v1/audio/transcriptions",
    };
    let model = match provider {
        "groq" => "whisper-large-v3",
        _ => "whisper-1",
    };
    let part = reqwest::blocking::multipart::Part::bytes(audio.to_vec())
        .file_name("voice.ogg").mime_str("audio/ogg").unwrap();
    let form = reqwest::blocking::multipart::Form::new()
        .text("model", model.to_string()).text("language", "ru").part("file", part);
    let resp = client.post(whisper_url)
        .header("Authorization", format!("Bearer {}", whisper_key))
        .multipart(form).timeout(Duration::from_secs(30))
        .send().map_err(|e| e.to_string())?;
    let parsed: serde_json::Value = serde_json::from_str(&resp.text().map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;

    Ok(Value::Str(parsed["text"].as_str().unwrap_or("").to_string()))
}
```

**Зависимость:** `reqwest` с feature `multipart` в Cargo.toml.

### Обработка в app.mlog

```mlog
route "/webhook/telegram" method=POST {
  let data = json_body()

  // Проверяем тип сообщения
  let has_voice = has_field(data, "message.voice")
  let chat_id = to_string(json_get(data, "message.chat.id"))
  let user_id = to_string(json_get(data, "message.from.id"))

  let owner_id = env("OWNER_TELEGRAM_ID")
  if user_id != owner_id then { return respond("200 ok") }

  // STT: голосовое → текст
  let text = ""
  if has_voice == 1.0 then {
    let file_id = json_get(data, "message.voice.file_id")
    let token = env("TELEGRAM_BOT_TOKEN")
    let whisper_key = env("WHISPER_API_KEY")
    let whisper_provider = env("WHISPER_PROVIDER")
    let text = whisper_transcribe(file_id, token, whisper_key, whisper_provider)
    send_message(chat_id, "Raspoznano: " + text)
  } else {
    let text = json_get(data, "message.text", "")
  }

  // Далее text обрабатывается как обычно — lockdown, routing, отделы...
}
```

**Ключевое:** используем `json_get(data, "message.voice.file_id")` — dot-path, без промежуточных let. `has_field(data, "message.voice")` проверяет наличие голосового. `send_message(chat_id, text)` — встроенный, без ручного http_post.

---

## Часть 2: TTS — ответы голосом

### Новый builtin: `tts_send(text, voice, bot_token, chat_id)` → String

Генерирует аудио через edge-tts и отправляет в Telegram:

```rust
fn builtin_tts_send(args: Vec<Value>) -> Result<Value, String> {
    let text = args[0].as_str()?;
    let voice = args[1].as_str()?;
    let bot_token = args[2].as_str()?;
    let chat_id = args[3].as_str()?;

    let output_path = format!("/tmp/tts_{}.mp3",
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis());

    // Генерация через edge-tts (subprocess)
    let status = std::process::Command::new("edge-tts")
        .args(&["--voice", voice, "--text", text, "--write-media", &output_path])
        .status().map_err(|e| e.to_string())?;
    if !status.success() { return Err("TTS failed".into()); }

    // Отправка в Telegram через sendVoice (multipart)
    let client = reqwest::blocking::Client::new();
    let audio = std::fs::read(&output_path).map_err(|e| e.to_string())?;
    let part = reqwest::blocking::multipart::Part::bytes(audio)
        .file_name("voice.ogg").mime_str("audio/mpeg").unwrap();
    let form = reqwest::blocking::multipart::Form::new()
        .text("chat_id", chat_id.to_string()).part("voice", part);
    let url = format!("https://api.telegram.org/bot{}/sendVoice", bot_token);
    client.post(&url).multipart(form).timeout(Duration::from_secs(30))
        .send().map_err(|e| e.to_string())?;

    let _ = std::fs::remove_file(&output_path);
    Ok(Value::Str("ok".to_string()))
}
```

### Логика ответа в app.mlog

После формирования reply любым отделом:

```mlog
    let voice_on = kv_get("voice_enabled")
    if voice_on == "true" then {
      if len(reply) < 200 then {
        let voice_name = kv_get("tts_voice")
        if len(voice_name) < 3 then { let voice_name = "ru-RU-DmitryNeural" }
        let token = env("TELEGRAM_BOT_TOKEN")
        let _ = tts_send(reply, voice_name, token, chat_id)
      }
    }
    send_message(chat_id, reply)
```

### Команды

```mlog
match text {
  starts_with "/voice on" then {
    kv_set("voice_enabled", "true")
    send_message(chat_id, "Golosovye otvety vklyucheny")
    return respond("200 ok")
  }
  starts_with "/voice off" then {
    kv_set("voice_enabled", "false")
    send_message(chat_id, "Golosovye otvety otklyucheny")
    return respond("200 ok")
  }
  starts_with "/voice male" then {
    kv_set("tts_voice", "ru-RU-DmitryNeural")
    send_message(chat_id, "Golos: muzhskoj (Dmitry)")
    return respond("200 ok")
  }
  starts_with "/voice female" then {
    kv_set("tts_voice", "ru-RU-SvetlanaNeural")
    send_message(chat_id, "Golos: zhenskij (Svetlana)")
    return respond("200 ok")
  }
}
```

### Обновить Dockerfile

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install edge-tts --break-system-packages
COPY bin/mlog /usr/local/bin/mlog
RUN chmod +x /usr/local/bin/mlog
WORKDIR /office
COPY . .
RUN mkdir -p /office/data /tmp
EXPOSE 10000
CMD ["mlog", "serve", "app.mlog"]
```

### Переменные окружения

```
WHISPER_API_KEY=gsk_...         # Groq ключ (бесплатный Whisper)
WHISPER_PROVIDER=groq           # "groq" или "openai"
```

---

## Итого: 2 новых builtin

| Builtin | Сигнатура | Назначение |
|---|---|---|
| `whisper_transcribe` | (file_id, bot_token, whisper_key, provider) → String | STT |
| `tts_send` | (text, voice, bot_token, chat_id) → String | TTS + отправка |

---

## Коммит

```bash
git commit -m "Voice: STT (Whisper) + TTS (Edge TTS) + /voice commands"
git push origin main
```

## Отчёт

```
### Результат Наряда №11

1. whisper_transcribe builtin: [✅/❌]
2. tts_send builtin: [✅/❌]
3. Голосовое → текст → обработка: [✅/❌]
4. Короткий ответ → голос: [✅/❌]
5. /voice on/off/male/female: [✅/❌]
6. edge-tts в Dockerfile: [✅/❌]
7. kv_set/kv_get для настроек: [✅/❌]
8. json_get с dot-path: [✅/❌]
9. send_message вместо http_post: [✅/❌]
10. git push: [✅/❌] [хэш]
11. Проблемы: [если есть]
```
