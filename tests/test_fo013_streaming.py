"""FO-013: стриминговая отправка Python-side — статусы, куски, voice-render."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-fo13-test")

import proxy.telegram as tg  # noqa: E402
import proxy.voice as voice_mod  # noqa: E402


class TestSplitLong:
    def test_short_text_single(self):
        assert tg.tg_split_long("Привет", limit=100) == ["Привет"]

    def test_paragraph_boundaries(self):
        blocks = ["A" * 900, "B" * 900, "C" * 900, "D" * 900, "E" * 900]
        text = "\n\n".join(blocks)
        parts = tg.tg_split_long(text, limit=2000)
        assert all(len(p) <= 2000 for p in parts)
        # абзацы не рвутся: каждый цельный блок целиком в одном куске
        for b in blocks:
            assert any(b in p for p in parts), "абзац разрезан"
        # без потерь: множество символов совпадает
        assert sorted("".join(parts).replace("\n", "")) == sorted(text.replace("\n", ""))
        assert len(parts) == 3  # 900*2+2=1802 ≤ 2000 → по два блока на кусок

    def test_giant_block_hard_split(self):
        text = "X" * 10000
        parts = tg.tg_split_long(text, limit=3800)
        assert all(len(p) <= 3800 for p in parts)
        assert sum(p.count("X") for p in parts) == 10000  # ни один символ не потерян


class TestStatusRateLimit:
    def test_second_status_cut(self, monkeypatch):
        sent = []
        monkeypatch.setattr(tg, "_tg_send_formatted", lambda cid, text, dept=None: sent.append(text) or "mid")
        tg._status_last.clear()
        assert tg.tg_status("111", "маршрутизирую") is True
        assert tg.tg_status("111", "анализирую") is False      # срезан лимитом
        assert tg.tg_status("222", "другой чат") is True       # другой чат — своя лимита
        assert tg.tg_status("111", "force", force=True) is True  # force проходит
        assert len(sent) == 3


class TestSendLong:
    def test_multi_part_sends_all(self, monkeypatch):
        sent = []
        monkeypatch.setattr(tg, "_tg_send_formatted", lambda cid, text, dept=None: sent.append(text) or "mid")
        monkeypatch.setattr(tg.time, "sleep", lambda s: None)
        blocks = [f"Параграф {i}. " + "текст " * 300 for i in range(4)]  # ~1800 знаков каждый
        text = "\n\n".join(blocks)
        ids = tg.tg_send_long("555", text, dept="osp")
        assert len(ids) == len(sent) == 2  # 4 абзаца ~1801 зн → 2 куска
        assert all(len(p) <= 3800 for p in sent)

    def test_short_text_one_message(self, monkeypatch):
        sent = []
        monkeypatch.setattr(tg, "_tg_send_formatted", lambda cid, text, dept=None: sent.append(text) or "mid")
        ids = tg.tg_send_long("555", "короткий ответ", dept="yana")
        assert ids == ["mid"] and sent == ["короткий ответ"]


class TestVoiceRender:
    def test_llm_rewrite_used(self, monkeypatch):
        monkeypatch.setattr(voice_mod, "call_llm", lambda dept, messages, command="": {
            "reply": "Короче говоря, ставка была повышена на пятьдесят базисных пунктов. " * 2})
        out = voice_mod.voice_render("## Отчёт ✓\n\n- ставка: +50 б.п.\n\n**Вердикт:** важно")
        assert "Короче говоря" in out
        assert "✓" not in out and "**" not in out

    def test_fallback_on_llm_failure(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("down")
        monkeypatch.setattr(voice_mod, "call_llm", boom)
        out = voice_mod.voice_render("## Отчёт\n\nТекст анализа ✓")
        assert "##" not in out and "✓" not in out  # деградация к чистому тексту
        assert "Текст анализа" in out

    def test_weak_reply_ignored(self, monkeypatch):
        monkeypatch.setattr(voice_mod, "call_llm", lambda dept, messages, command="": {"reply": "[Oshibka] Vse providery nedostupny"})
        out = voice_mod.voice_render("Нормальный текст для озвучки, достаточно длинный чтобы пройти лимит проверки. " * 3)
        assert "[Oshibka]" not in out
        assert "Нормальный текст" in out


class TestEndpoints:
    def test_tg_status_endpoint(self, monkeypatch):
        import llm_proxy
        import proxy.routes_core as _rc
        calls = []
        monkeypatch.setattr(_rc, "tg_status", lambda cid, text, dept=None, force=False: calls.append((cid, text, dept, force)) or True)
        c = llm_proxy.app.test_client()
        r = c.post("/tg-status", json={"chat_id": "1", "text": "анализирую", "dept": "osp"})
        assert r.status_code == 200 and r.get_json()["sent"] is True
        assert calls[0] == ("1", "анализирую", "osp", False)
        assert c.post("/tg-status", json={"text": "x"}).status_code == 400

    def test_tg_send_long_endpoint(self, monkeypatch):
        import llm_proxy
        import proxy.routes_core as _rc
        monkeypatch.setattr(_rc, "tg_send_long", lambda cid, text, dept=None, limit=3800: ["m1", "m2"])
        c = llm_proxy.app.test_client()
        r = c.post("/tg-send-long", json={"chat_id": "1", "text": "длинный ответ"})
        assert r.get_json()["messages_sent"] == 2
        assert c.post("/tg-send-long", json={"chat_id": "1"}).status_code == 400
