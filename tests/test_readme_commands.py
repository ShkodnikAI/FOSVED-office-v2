"""#250: гвард README «Команды бота» — расхождение live-vs-docs = 0 в обе стороны.

Live-набор извлекается из app.mlog (обработчики starts_with и точные ==).
Документированный набор — все backticked `/токены` внутри раздела «Команды бота».
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.mlog").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _live_commands() -> set:
    live = set()
    for ln in APP.splitlines():
        if ln.strip().startswith("//"):
            continue
        for m in re.finditer(r'starts_with\(text,\s*"/([a-z0-9_ -]+?)"?\)', ln):
            live.add(m.group(1).strip())
        for m in re.finditer(r'text\s*==\s*"/([a-z0-9_]+)"', ln):
            live.add(m.group(1).strip())
    return live


def _readme_section() -> str:
    m = re.search(r"^## Команды бота$(.*?)(?=^## )", README, re.M | re.S)
    assert m, "раздел «Команды бота» не найден в README"
    return m.group(1)


def test_every_live_command_documented():
    sec = _readme_section()
    missing = sorted(c for c in _live_commands() if f"`/{c}`" not in sec)
    assert not missing, f"живые команды без документации в README: {missing}"


def test_no_dead_commands_documented():
    sec = _readme_section()
    live = _live_commands()
    documented = set(re.findall(r"`/([a-z0-9_ -]+)`", sec))
    dead = sorted(d for d in documented if d not in live)
    assert not dead, f"в README документированы несуществующие команды: {dead}"
