"""Барьер сборки без Docker: всё, что Dockerfile копирует или делает исполняемым,
должно существовать в git и не отрезаться .dockerignore.

Инциденты: 2026-09-25 (chmod удалённого mlog-023) и 2026-09-30/10-01
(COPY bin/mlog-025 после его удаления в #399) — каждый деплой падал на сборке,
прод сутки ехал на старом коде. CI (docker-build) в это время не работал (#443).
"""
import fnmatch
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return set(out.split())


def _dockerignore():
    p = ROOT / ".dockerignore"
    if not p.exists():
        return [], []
    excl, incl = [], []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        (incl if line.startswith("!") else excl).append(line.lstrip("!"))
    return excl, incl


def _ignored(path, excl, incl):
    hit = any(fnmatch.fnmatch(path, pat) or path.startswith(pat.rstrip("/*") + "/") for pat in excl)
    if hit and any(fnmatch.fnmatch(path, pat) or path == pat for pat in incl):
        return False
    return hit


def _dockerfile_lines():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    return text.replace("\\\n", " ").splitlines()


def test_copy_sources_exist_in_git_and_context():
    tracked = _tracked()
    excl, incl = _dockerignore()
    missing = []
    for line in _dockerfile_lines():
        m = re.match(r"\s*COPY\s+((?:--\S+\s+)*)(.+)\s+(\S+)\s*$", line)
        if not m or "--from" in m.group(1):
            continue
        for src in m.group(2).split():
            if src in (".", "./"):
                continue
            exists = src in tracked or any(t.startswith(src.rstrip("/") + "/") for t in tracked)
            if not exists:
                missing.append(f"{src}: нет в git")
            elif src in tracked and _ignored(src, excl, incl):
                missing.append(f"{src}: отрезан .dockerignore")
    assert not missing, "Dockerfile копирует то, чего нет в контексте сборки: " + "; ".join(missing)


def test_chmod_targets_from_repo_exist():
    tracked = _tracked()
    missing = []
    for line in _dockerfile_lines():
        if "chmod" not in line:
            continue
        # только сегменты самой команды chmod (после && может идти mkdir и т.п.)
        chmod_parts = [seg for seg in re.split(r"&&|;", line) if "chmod" in seg]
        for path in re.findall(r"/office/(\S+)", " ".join(chmod_parts)):
            path = path.rstrip("\\;&")
            if path and not (path in tracked or any(t.startswith(path.rstrip("/") + "/") for t in tracked)):
                missing.append(path)
    assert not missing, "Dockerfile делает исполняемыми файлы, которых нет в git: " + ", ".join(missing)
