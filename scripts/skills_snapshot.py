#!/usr/bin/env python3
"""FO-012 (issue #72): генерация снапшота skills/ — архив + манифест.

skills/ больше не живёт в git (см. docs/repo-hygiene.md). Каноничный способ
обновить снапшот после изменения скиллов:

    python3 scripts/skills_snapshot.py            # архив + манифест в artifacts/
    # затем: создать Release с тегом из манифеста, залить ассет,
    # закоммитить обновлённый skills-manifest.json

Скрипт только готовит артефакты — публикация релиза остаётся ручным шагом
(сознательно: снапшот — событие с версией, а не побочный эффект).
"""

import hashlib
import json
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE / "skills"
ARTIFACTS = BASE / "artifacts"


def main():
    if not SKILLS_DIR.is_dir():
        print(f"ERROR: {SKILLS_DIR} не найден — скиллы не развёрнуты?")
        return 1

    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tag = f"skills-snapshot-{date_tag}"
    asset_name = f"{tag}.tar.gz"

    ARTIFACTS.mkdir(exist_ok=True)
    tar_path = ARTIFACTS / asset_name

    entries = {}
    for name in sorted(os.listdir(SKILLS_DIR)):
        p = SKILLS_DIR / name
        if not p.is_dir():
            continue
        skill_md = p / "SKILL.md"
        entries[name] = (
            hashlib.sha256(skill_md.read_bytes()).hexdigest()[:16]
            if skill_md.exists()
            else None
        )

    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(SKILLS_DIR, arcname="skills")

    sha = hashlib.sha256(tar_path.read_bytes()).hexdigest()

    manifest = {
        "snapshot_tag": tag,
        "snapshot_asset": asset_name,
        "snapshot_sha256": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "skills_count": len(entries),
        "note": (
            "Скиллы живут вне git (наряд FO-012, issue #72). Восстановление: "
            "scripts/bootstrap_skills.sh. Хеш — sha256(SKILL.md), первые 16 "
            "символов; null = SKILL.md отсутствует."
        ),
        "skills": entries,
    }
    manifest_path = BASE / "skills-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"tag:       {tag}")
    print(f"asset:     {tar_path} ({tar_path.stat().st_size // 1024 // 1024} МБ)")
    print(f"sha256:    {sha}")
    print(f"skills:    {len(entries)}")
    print(f"manifest:  {manifest_path}")
    print("Дальше: создайте Release с этим тегом, залейте ассет, закоммитьте манифест.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
