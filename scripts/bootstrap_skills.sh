#!/bin/bash
# FO-012 (issue #72): восстановление skills/ из релиз-артефакта.
# #755 SKILLS-1 (аудит 22.11): токен умер ~15.11 — навыки не грузились
# неделю, никто не заметил. Три правки наряда:
#   A.1 кэш на постоянном диске: /var/data/skills_cache/<tag>/ + симлинк
#       skills → кэш; старт при живом кэше НЕ ходит в сеть вовсе.
#   A.2 код HTTP-ошибки в лог: не молчаливый curl -sf, а «HTTP 401|403|404».
#   A.3 тревога в брифе — не здесь: sentinel-статус читает утренний бриф
#       (proxy/routes_sched.py, skills_status_line) — владелец видит.
#
# Скиллы (249 каталогов, ~1100 файлов) не лежат в git (FO-012) — каноничный
# снапшот живёт в GitHub Release этого же репозитория:
#   tag:    из skills-manifest.json (snapshot_tag)
#   asset:  snapshot_asset (tar.gz), sha256 — snapshot_sha256
#
# Логика (порядок — от самого дешёвого):
#   1. skills/ на месте (сентинел) — ничего не делаем (рестарт без деплоя).
#   2. Кэш тега из манифеста на /var/data есть и sha совпадает — разворот
#      из кэша, БЕЗ сети (наряд A.1: «второй старт без токена»).
#   3. Иначе качаем ассет релиза (нужен токен), проверяем sha, кладём в
#      кэш /var/data/skills_cache/<tag>/ и разворачиваем.
#   4. Провал — НЕ фатален: офис стартует в деградированном режиме
#      (read_file_or("skills/...") вернёт пусто), WARNING в лог, строка
#      тревоги в утреннем брифе (A.3).
#
# Токены пробуются в порядке: GITHUB_TOKEN_SKILLS, GITHUB_TOKEN_METALOGOS,
# GITHUB_TOKEN, GH_TOKEN. Для приватного репо нужен token с content:read.
# Токен в лог НЕ печатается (запрет наряда).

set -u

cd "$(dirname "$0")/.." || exit 1

SENTINEL="skills/deconstruct/SKILL.md"
MANIFEST="skills-manifest.json"
# Постоянный диск Render (entrypoint.sh: DATABASE_PATH=/var/data).
# Локально/CI /var/data может не существовать — кэш отключён, фолбэк-путь.
CACHE_ROOT="${SKILLS_CACHE_ROOT:-/var/data/skills_cache}"

# ── 1. Уже на месте? (рестарт контейнера без пересборки образа) ─────────────
if [ -f "$SENTINEL" ]; then
  N=$(ls skills/ 2>/dev/null | wc -l)
  echo "[skills] OK: skills/ развёрнут (${N} записей) — bootstrap не нужен"
  exit 0
fi

echo "[skills] skills/ отсутствует — восстановление"

# ── 2. Манифест ───────────────────────────────────────────────────────────────
if [ ! -f "$MANIFEST" ]; then
  echo "[skills] WARNING: ${MANIFEST} не найден — скачайте снапшот вручную из Releases"
  exit 0
fi

TAG=$(python3 -c "import json;print(json.load(open('${MANIFEST}'))['snapshot_tag'])" 2>/dev/null)
ASSET=$(python3 -c "import json;print(json.load(open('${MANIFEST}'))['snapshot_asset'])" 2>/dev/null)
EXPECT_SHA=$(python3 -c "import json;print(json.load(open('${MANIFEST}')).get('snapshot_sha256',''))" 2>/dev/null)

if [ -z "${TAG:-}" ] || [ -z "${ASSET:-}" ]; then
  echo "[skills] WARNING: манифест повреждён (нет тега/ассета) — пропуск"
  exit 0
fi

# ── 3. Кэш на постоянном диске (#755 A.1) ─────────────────────────────────────
# Кэш переживает рестарт контейнера (постоянный диск): второй старт без
# токена/сети разворачивает навыки отсюда. sha кэша сверяется с манифестом —
# кэш не может подсунуть чужой/битый снапшот.
CACHE_DIR="${CACHE_ROOT}/${TAG}"
if [ -d "$CACHE_DIR" ] && [ -f "${CACHE_DIR}/${SENTINEL}" ]; then
  CACHE_OK=1
  if [ -n "$EXPECT_SHA" ]; then
    CACHED_SHA=$(cat "${CACHE_DIR}/.snapshot.sha256" 2>/dev/null || true)
    if [ "$CACHED_SHA" != "$EXPECT_SHA" ]; then
      CACHE_OK=0
      echo "[skills] WARNING: кэш ${TAG} не проходит sha (${CACHED_SHA:0:16}… ≠ ${EXPECT_SHA:0:16}…) — кэш игнорирую"
    fi
  fi
  if [ "$CACHE_OK" = "1" ]; then
    rm -rf skills 2>/dev/null || true
    if ln -s "$CACHE_DIR/skills" skills 2>/dev/null; then
      N=$(ls skills/ 2>/dev/null | wc -l)
      echo "[skills] OK: из кэша ${TAG} (${N} записей) — сеть не нужна"
      exit 0
    fi
  fi
fi

# ── 4. Токен ──────────────────────────────────────────────────────────────────
TOKEN=""
for VAR in GITHUB_TOKEN_SKILLS GITHUB_TOKEN_METALOGOS GITHUB_TOKEN GH_TOKEN; do
  VAL=$(printenv "$VAR" 2>/dev/null || true)
  if [ -n "$VAL" ] && [ "$VAL" != "" ] && ! printf '%s' "$VAL" | grep -q "^\["; then
    TOKEN="$VAL"
    echo "[skills] токен найден в $VAR"
    break
  fi
done

if [ -z "$TOKEN" ]; then
  echo "[skills] WARNING: ни одного GitHub-токена в env (GITHUB_TOKEN_SKILLS/GITHUB_TOKEN_METALOGOS/GITHUB_TOKEN/GH_TOKEN) не найдено."
  echo "[skills] WARNING: скиллы НЕ восстановлены — скилл-контекст департаментов будет пустым."
  echo "[skills] WARNING: выставьте GITHUB_TOKEN_SKILLS (token с read-доступом к репо) и перезапустите, или распакуйте архив вручную."
  exit 0
fi

# ── 5. Скачивание + код ответа в лог (#755 A.2) + проверка + распаковка ──────
TMP_TAR=$(mktemp /tmp/skills-snapshot.XXXXXX.tar.gz)
TMP_JSON=$(mktemp /tmp/skills-rel.XXXXXX.json)
API_URL="https://api.github.com/repos/${GITHUB_REPOSITORY:-ShkodnikAI/FOSVED-office-v2}/releases/tags/${TAG}"

echo "[skills] запрос метаданных релиза ${TAG}..."
# #755 A.2: код ответа — в лог, не молчаливый curl -sf. 401/403 — токен
# истёк/без доступа, 404 — релиз удалён. Токен в строке НЕ печатается.
META_CODE=$(curl -sL -o "$TMP_JSON" -w "%{http_code}" \
  -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
  "$API_URL" 2>/dev/null || echo "000")
if [ "$META_CODE" != "200" ]; then
  echo "[skills] WARNING: HTTP ${META_CODE} на метаданных релиза ${TAG} — скиллы не восстановлены"
  rm -f "$TMP_TAR" "$TMP_JSON"
  exit 0
fi
if ! python3 -c "import json;json.load(open('${TMP_JSON}'))" 2>/dev/null; then
  echo "[skills] WARNING: релиз ${TAG}: ответ не JSON (HTTP ${META_CODE}) — скиллы не восстановлены"
  rm -f "$TMP_TAR" "$TMP_JSON"
  exit 0
fi

DL_URL=$(python3 -c "
import json
d=json.load(open('${TMP_JSON}'))
for a in d.get('assets',[]):
    if a.get('name')=='${ASSET}':
        print(a.get('url',''))
        break
" 2>/dev/null)
rm -f "$TMP_JSON"

if [ -z "$DL_URL" ]; then
  echo "[skills] WARNING: ассет ${ASSET} не найден в релизе ${TAG} — скиллы не восстановлены"
  rm -f "$TMP_TAR"
  exit 0
fi

echo "[skills] скачивание ассета..."
# Accept: application/octet-stream → GitHub отдаёт бинарник ассета
HTTP_CODE=$(curl -sL -o "$TMP_TAR" -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/octet-stream" "$DL_URL")
if [ "$HTTP_CODE" != "200" ]; then
  echo "[skills] WARNING: скачивание не удалось (HTTP ${HTTP_CODE}) — скиллы не восстановлены"
  rm -f "$TMP_TAR"
  exit 0
fi

# ── 6. Целостность ───────────────────────────────────────────────────────────
GOT_SHA=$(sha256sum "$TMP_TAR" 2>/dev/null | cut -d' ' -f1)
if [ -n "$EXPECT_SHA" ] && [ "$GOT_SHA" != "$EXPECT_SHA" ]; then
  echo "[skills] WARNING: sha256 не совпал (ожидалось ${EXPECT_SHA:0:16}..., получено ${GOT_SHA:0:16}...) — архив не распакован"
  rm -f "$TMP_TAR"
  exit 0
fi
echo "[skills] sha256 OK"

# ── 7. Кэш + разворот (#755 A.1) ─────────────────────────────────────────────
# Сначала — в кэш на постоянном диске (временный каталог + rename = атомарно),
# затем skills → симлинк на кэш. Следующий рестарт стартует без сети;
# старые теги кэша удаляются ПОСЛЕ успешного разворота нового (наряд).
if mkdir -p "$CACHE_ROOT" 2>/dev/null; then
  STAGE=$(mktemp -d "${CACHE_ROOT}/.stage.XXXXXX")
  if tar -xzf "$TMP_TAR" -C "$STAGE" 2>/dev/null && [ -f "${STAGE}/${SENTINEL}" ]; then
    printf '%s' "$GOT_SHA" > "${STAGE}/.snapshot.sha256"
    rm -rf "${CACHE_DIR}" 2>/dev/null || true
    if mv "$STAGE" "$CACHE_DIR" 2>/dev/null; then
      rm -f "$TMP_TAR"
      rm -rf skills 2>/dev/null || true
      if ln -s "$CACHE_DIR/skills" skills 2>/dev/null; then
        # старые теги и мусор стадий больше не нужны (наряд: чистка после
        # успешного разворота нового)
        find "$CACHE_ROOT" -maxdepth 1 -mindepth 1 -type d \
          ! -path "$CACHE_DIR" -exec rm -rf {} + 2>/dev/null || true
        N=$(ls skills/ 2>/dev/null | wc -l)
        echo "[skills] OK: из релиза ${TAG} → кэш + skills/ (${N} записей)"
        exit 0
      fi
    fi
  fi
  rm -rf "$STAGE" 2>/dev/null || true
fi

# Фолбэк: кэш недоступен (нет /var/data — локальный запуск/CI) — как прежде,
# распаковка в корень репо
tar -xzf "$TMP_TAR" -C .
rm -f "$TMP_TAR"
if [ -f "$SENTINEL" ]; then
  N=$(ls skills/ 2>/dev/null | wc -l)
  echo "[skills] восстановлено: skills/ развёрнут (${N} записей) из ${TAG} (без кэша)"
else
  echo "[skills] WARNING: распаковка выполнена, но сентинел ${SENTINEL} не найден — проверьте структуру архива"
fi
