#!/bin/bash
# FO-012 (issue #72): восстановление skills/ из релиз-артефакта.
#
# Скиллы (248 каталогов, ~1100 файлов) больше не лежат в git — репо похудело
# на ~62 МБ. Каноничный снапшот живёт в GitHub Release этого же репозитория:
#   tag:    skills-snapshot-2026-09-12
#   asset:  skills-snapshot-2026-09-12.tar.gz
# Манифест skills-manifest.json (в git) фиксирует тег снапшота, sha256 архива
# и список скиллов с хешами SKILL.md.
#
# Логика:
#   1. Если skills/ уже развёрнут (сентинел на месте) — ничего не делаем.
#   2. Иначе качаем ассет релиза из манифеста (нужен токен с доступом к репо)
#      и распаковываем в корень.
#   3. Провал — НЕ фатален: офис стартует в деградировавшем режиме
#      (read_file("skills/...") вернёт пусто), в лог будет выведено WARNING.
#
# Токены пробуются в порядке: GITHUB_TOKEN_SKILLS, GITHUB_TOKEN_METALOGOS,
# GITHUB_TOKEN, GH_TOKEN. Для приватного репо нужен token с content:read.

set -u

cd "$(dirname "$0")/.." || exit 1

SENTINEL="skills/deconstruct/SKILL.md"
MANIFEST="skills-manifest.json"

# ── 1. Уже на месте? ─────────────────────────────────────────────────────────
if [ -f "$SENTINEL" ]; then
  N=$(ls skills/ 2>/dev/null | wc -l)
  echo "[skills] OK: skills/ развёрнут (${N} записей) — bootstrap не нужен"
  exit 0
fi

echo "[skills] skills/ отсутствует — восстановление из релиз-артефакта"

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

# ── 3. Токен ──────────────────────────────────────────────────────────────────
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

# ── 4. Скачивание + проверка + распаковка ────────────────────────────────────
TMP_TAR=$(mktemp /tmp/skills-snapshot.XXXXXX.tar.gz)
API_URL="https://api.github.com/repos/${GITHUB_REPOSITORY:-ShkodnikAI/FOSVED-office-v2}/releases/tags/${TAG}"

echo "[skills] запрос метаданных релиза ${TAG}..."
REL_JSON=$(curl -sf -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" "$API_URL")
if [ -z "$REL_JSON" ]; then
  echo "[skills] WARNING: релиз ${TAG} недоступен (токен без доступа? релиз удалён?) — скиллы не восстановлены"
  rm -f "$TMP_TAR"
  exit 0
fi

DL_URL=$(printf '%s' "$REL_JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for a in d.get('assets',[]):
    if a.get('name')=='${ASSET}':
        print(a.get('url',''))
        break
" 2>/dev/null)

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

# ── 5. Целостность ───────────────────────────────────────────────────────────
if [ -n "$EXPECT_SHA" ]; then
  GOT_SHA=$(sha256sum "$TMP_TAR" 2>/dev/null | cut -d' ' -f1)
  if [ "$GOT_SHA" != "$EXPECT_SHA" ]; then
    echo "[skills] WARNING: sha256 не совпал (ожидалось ${EXPECT_SHA:0:16}..., получено ${GOT_SHA:0:16}...) — архив не распакован"
    rm -f "$TMP_TAR"
    exit 0
  fi
  echo "[skills] sha256 OK"
fi

tar -xzf "$TMP_TAR" -C .
rm -f "$TMP_TAR"

if [ -f "$SENTINEL" ]; then
  N=$(ls skills/ 2>/dev/null | wc -l)
  echo "[skills] восстановлено: skills/ развёрнут (${N} записей) из ${TAG}"
else
  echo "[skills] WARNING: распаковка выполнена, но сентинел ${SENTINEL} не найден — проверьте структуру архива"
fi
