"""FO-016 tests: компакция контекста — budget + prune + summarize + offload.

Наряд #82 (пакет G). Критерии «сделано, когда»:
- синтетическая сессия >100 ходов не превышает бюджет (prune/summarize);
- трейсы показывают экономию; плейсхолдер цитируем (restore_tool_output);
- отказ диска не роняет диалог; offload-файлы чистятся по ретеншну.
"""
import json
import os
import sys
import time
import re

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before llm_proxy import (same contract as test_security.py)
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo16-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402
from proxy import compaction as comp  # noqa: E402
from proxy.providers import (  # noqa: E402
    COMBO_CHAINS, _estimate_tokens, _compress_messages, _compaction_summarize,
)

STD_CHAIN = COMBO_CHAINS["fosved-standard"]


def _turns(n, chars=1400, dept_note="x"):
    """Синтетический диалог: n пар user/assistant по ~chars символов."""
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"Вопрос {i}: " + dept_note * chars})
        msgs.append({"role": "assistant", "content": f"Ответ {i}: " + dept_note * chars})
    return msgs


@pytest.fixture()
def tool_dir(tmp_path, monkeypatch):
    d = tmp_path / "tool_output"
    d.mkdir()
    monkeypatch.setattr(comp, "TOOL_OUTPUT_DIR", str(d))
    return str(d)


@pytest.fixture()
def no_trace(monkeypatch):
    recs = []
    monkeypatch.setattr(comp, "_write_llm_trace", lambda r: recs.append(r))
    return recs


# ────────────────────────── бюджет ──────────────────────────

class TestBudget:
    def test_floor_over_chain_minus_reserve(self):
        b = comp.get_context_budget("qa", chain=STD_CHAIN)
        # флор цепи — deepseek 65536; резерв std-департамента 8192
        assert b == 65536 - comp.resolve_output_reserve("qa")
        assert comp.resolve_output_reserve("yana") == 16384  # большой департамент

    def test_big_dept_reserve(self):
        b_big = comp.get_context_budget("yana", chain=STD_CHAIN)
        b_std = comp.get_context_budget("qa", chain=STD_CHAIN)
        assert b_std - b_big == 8192

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("FOSVED_CTX_MAX_TOKENS", "1500")
        assert comp.get_context_budget("qa", chain=STD_CHAIN) == 1500

    def test_unknown_provider_conservative(self):
        b = comp.get_context_budget("qa", chain=[("mystery", ["m1"])])
        assert b == 32768 - comp.resolve_output_reserve("qa")

    def test_estimate_tokens_compat(self):
        msgs = [{"role": "user", "content": "a" * 100}]
        assert _estimate_tokens(msgs) == comp.estimate_tokens(msgs) == 50


# ────────────────────────── конвейер ──────────────────────────

class TestCompactionPipeline:
    def test_small_session_untouched(self, tool_dir, no_trace):
        msgs = [{"role": "system", "content": "sys"}] + _turns(5)
        out, stats = comp.compact_context(msgs, "qa", chain=STD_CHAIN)
        assert out == msgs
        assert stats["strategy"] == "none"
        assert no_trace == []  # ничего не случилось — трейса нет

    def test_120_turns_within_budget_prune(self, tool_dir, no_trace):
        """Критерий наряда: синтетическая сессия >100 ходов не превышает бюджет."""
        msgs = [{"role": "system", "content": "sys prompt"}] + _turns(120)
        assert comp.estimate_tokens(msgs) > comp.get_context_budget("qa", chain=STD_CHAIN)
        out, stats = comp.compact_context(msgs, "qa", chain=STD_CHAIN)
        assert stats["strategy"] in ("prune", "prune+summarize")
        assert stats["pruned"] > 100  # старые реплики очищены
        assert stats["tokens_after"] <= stats["budget"]
        # плейсхолдеры на месте
        assert any("[очищено:" in m.get("content", "") for m in out)
        # system-промпт цел
        assert out[0]["content"] == "sys prompt"

    def test_prune_protects_recent_tail(self, tool_dir, no_trace):
        msgs = [{"role": "system", "content": "s"}] + _turns(120)
        out, stats = comp.compact_context(msgs, "qa", chain=STD_CHAIN)
        # последний ход не тронут (verbatim)
        assert out[-1]["content"] == msgs[-1]["content"]
        assert out[-2]["content"] == msgs[-2]["content"]
        # хвост не содержит плейсхолдеров
        tail = out[-6:]
        assert not any("[очищено:" in m.get("content", "") for m in tail)

    def test_summarize_replays_last_user(self, tool_dir, no_trace, monkeypatch):
        monkeypatch.setenv("FOSVED_CTX_MAX_TOKENS", "1200")
        # реплики по 200 токенов — ниже prune-порога (256) → суммаризация
        msgs = ([{"role": "system", "content": "s"}] + _turns(15, chars=400)
                + [{"role": "user", "content": "ФИНАЛЬНЫЙ ВОПРОС: что решили?"}])
        calls = []

        def fake_summarize(prompt_msgs):
            calls.append(prompt_msgs)
            return {"reply": "КЛЮЧЕВЫЕ ФАКТЫ: владелец решил X"}

        out, stats = comp.compact_context(msgs, "qa", chain=STD_CHAIN,
                                          summarize_fn=fake_summarize)
        assert stats["strategy"] == "summarize"
        assert stats["replayed"] is True
        assert stats["tokens_after"] <= stats["budget"]
        # сводка присутствует, последний user-ход дословно
        assert any("КЛЮЧЕВЫЕ ФАКТЫ" in m.get("content", "") for m in out)
        assert out[-1]["content"] == "ФИНАЛЬНЫЙ ВОПРОС: что решили?"
        assert out[-1]["role"] == "user"
        assert len(calls) == 1  # один вызов дешёвой модели

    def test_summarize_failure_hard_degrade(self, tool_dir, no_trace, monkeypatch):
        """Отказ суммаризатора не роняет диалог — детерминированная деградация."""
        monkeypatch.setenv("FOSVED_CTX_MAX_TOKENS", "1200")
        msgs = [{"role": "system", "content": "s"}] + _turns(15, chars=400)
        out, stats = comp.compact_context(
            msgs, "qa", chain=STD_CHAIN,
            summarize_fn=lambda p: (_ for _ in ()).throw(RuntimeError("groq down")))
        assert stats["summarized"] == 0 or stats["pruned"] >= 0
        assert stats["tokens_after"] < stats["tokens_before"]  # середина отсечена
        assert out[-1]["content"] == msgs[-1]["content"]  # последний ход цел

    def test_trace_written_with_metrics(self, tool_dir, no_trace):
        msgs = [{"role": "system", "content": "s"}] + _turns(120)
        comp.compact_context(msgs, "qa", chain=STD_CHAIN)
        rec = [r for r in no_trace if r.get("event") == "compaction"]
        assert len(rec) == 1
        r = rec[0]
        assert r["dept"] == "qa"
        assert r["tokens_saved"] == r["tokens_before"] - r["tokens_after"]
        assert r["pruned_msgs"] > 0
        assert r["strategy"] in ("prune", "prune+summarize")
        assert "budget" in r and "last_user_replayed" in r

    def test_dialog_history_part_record(self, tool_dir, no_trace, monkeypatch):
        """Запись-заготовка Part #83 ({"part_type":"compaction"}) в dialog_history."""
        inserts = []
        orig_query = comp._query
        monkeypatch.setattr(comp, "_query",
                            lambda sql, params=(), fetch=False: inserts.append((sql, params)))
        msgs = [{"role": "system", "content": "s"}] + _turns(120)
        comp.compact_context(msgs, "qa", chain=STD_CHAIN, chat_id="4242")
        assert len(inserts) == 1
        sql, params = inserts[0]
        assert "INSERT INTO dialog_history" in sql
        payload = json.loads(params[2])
        assert payload["part_type"] == "compaction"
        assert payload["pruned"] > 0
        # без chat_id записи нет
        inserts.clear()
        comp.compact_context(msgs, "qa", chain=STD_CHAIN)  # chat_id=None
        assert inserts == []
        monkeypatch.setattr(comp, "_query", orig_query)


# ────────────────────────── offload ──────────────────────────

class TestOffload:
    def _giant_tool_msg(self, lines=2200):
        body = "\n".join(f"line-{i:05d} some tool output payload" for i in range(lines))
        return {"role": "tool", "name": "db_query", "content": body}

    def test_giant_tool_output_offloaded(self, tool_dir, no_trace):
        original = self._giant_tool_msg()
        msgs = [{"role": "system", "content": "s"}, original]
        out, stats = comp.compact_context(msgs, "qa", chain=STD_CHAIN)
        assert stats["offloaded"] == 1
        ph = out[1]["content"]
        m = re.search(r"path=(\S+)", ph)
        assert m, "плейсхолдер обязан нести путь к оригиналу"
        assert "lines=2200" in ph and "[…]" in ph
        # цитируемость: оригинал восстанавливается из файла
        restored = comp.restore_tool_output(m.group(1))
        assert restored == original["content"]
        # файл лежит в хранилище
        assert os.path.isfile(os.path.join(tool_dir, m.group(1)))

    def test_small_tool_output_kept(self, tool_dir, no_trace):
        small = {"role": "tool", "name": "db_query", "content": "ok, 3 rows"}
        out, stats = comp.compact_context(
            [{"role": "system", "content": "s"}, small], "qa", chain=STD_CHAIN)
        assert stats["offloaded"] == 0
        assert out[1]["content"] == "ok, 3 rows"

    def test_user_assistant_not_offloaded(self, tool_dir, no_trace):
        big_user = {"role": "user", "content": "u" * 60000}
        out, stats = comp.compact_context(
            [{"role": "system", "content": "s"}, big_user], "qa", chain=STD_CHAIN)
        # offload — только tool/function; user-текст не трогается offload'ом
        assert stats["offloaded"] == 0
        assert out[1]["content"] == big_user["content"]

    def test_disk_failure_does_not_kill_dialog(self, tool_dir, no_trace, monkeypatch):
        """Критерий наряда: отказ диска не роняет диалог."""
        def boom(content, dept):
            raise OSError("No space left on device")
        monkeypatch.setattr(comp, "_write_offload_file", boom)
        giant = self._giant_tool_msg()
        out, stats = comp.compact_context(
            [{"role": "system", "content": "s"}, giant], "qa", chain=STD_CHAIN)
        assert stats["offloaded"] == 0
        assert out[1]["content"] == giant["content"]  # сообщение сохранено как есть

    def test_retention_cleanup(self, tool_dir, no_trace):
        day = "2026-01-01"
        d = os.path.join(tool_dir, day)
        os.makedirs(d)
        old_f = os.path.join(d, "old.txt")
        new_f = os.path.join(d, "new.txt")
        open(old_f, "w").write("old")
        open(new_f, "w").write("new")
        week_ago = time.time() - 8 * 86400
        os.utime(old_f, (week_ago, week_ago))
        removed = comp.cleanup_tool_output_files(retention_days=7, force=True)
        assert removed == 1
        assert not os.path.exists(old_f)
        assert os.path.exists(new_f)


# ────────────────────────── совместимость ──────────────────────────

class TestLegacyCompat:
    def test_compress_messages_wrapper(self, tool_dir, no_trace):
        """Старое имя _compress_messages работает и возвращает (msgs, saved)."""
        msgs = [{"role": "system", "content": "s"}] + _turns(120)
        out, saved = _compress_messages(msgs, "qa")
        assert saved > 0
        assert len(out) == len(msgs)

    def test_compress_messages_small(self, tool_dir, no_trace):
        msgs = _turns(3)
        out, saved = _compress_messages(msgs, "qa")
        assert saved == 0 and out == msgs

    def test_summarize_fn_signature(self):
        """_compaction_summarize передаётся как summarize_fn: возвращает None
        при отказе провайдеров (не бросает исключение)."""
        res = _compaction_summarize([{"role": "user", "content": "test"}])
        # в тестовом окружении ключей нет — ожидаем None или dict без краха
        assert res is None or isinstance(res, dict)

    def test_facade_exports(self):
        for name in ("compact_context", "get_context_budget", "PROVIDER_CONTEXT_LIMITS",
                     "restore_tool_output", "cleanup_tool_output_files", "TOOL_OUTPUT_DIR"):
            assert hasattr(llm_proxy, name), f"facade lost {name}"
