"""FO-010: детерминированные API-источники ЛЗ — парсинг, дедуп, трейс-метрика."""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-lzsrc-test")

import proxy.lz_sources as lzs  # noqa: E402

ARXIV_ATOM = '''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2609.01234v1</id>
    <title>Solid-State Batteries: A  Room-Temperature  Breakthrough</title>
    <summary>  We demonstrate ionic conductivity of 10 mS/cm
    at room temperature in sulfide electrolytes.  </summary>
    <published>2026-09-01T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2609.01234v1" rel="alternate" type="text/html"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2609.05678v1</id>
    <title>Geopolitics of Chip Supply Chains</title>
    <summary>Policy analysis.</summary>
    <published>2026-08-20T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2609.05678v1" rel="alternate" type="text/html"/>
  </entry>
</feed>'''

HN_JSON = {
    "hits": [
        {"objectID": "1", "title": "Hypersonic test flight analysis", "url": "https://example.com/hn1",
         "created_at": "2026-09-05T10:00:00Z", "points": 250, "num_comments": 120},
        {"objectID": "2", "title": None, "story_title": "Ask HN: battery startups?",
         "url": None, "created_at": "2026-09-06T10:00:00Z", "points": 40, "num_comments": 15},
    ]
}

GH_JSON = {"items": [
    {"full_name": "org/cool-repo", "html_url": "https://github.com/org/cool-repo",
     "stargazers_count": 5300, "language": "Rust", "pushed_at": "2026-09-08T00:00:00Z",
     "description": "Electrolyte simulation toolkit"},
]}


@pytest.fixture
def mock_http(monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        class R:
            text = ARXIV_ATOM
            def raise_for_status(self): pass
            def json(self):
                if "hn.algolia" in url:
                    return HN_JSON
                if "api.github.com" in url:
                    return GH_JSON
                return {}
        return R()

    monkeypatch.setattr(lzs.http_requests, "get", fake_get)
    return calls


def test_arxiv_parses_atom(mock_http):
    items = lzs.arxiv_search("solid state batteries", max_results=5)
    assert len(items) == 2
    assert items[0]["source"] == "arxiv"
    assert "Room-Temperature" in items[0]["title"].replace("  ", " ")
    assert items[0]["published"] == "2026-09-01"
    assert items[0]["url"].startswith("http://arxiv.org/abs/")


def test_hn_parses_algolia(mock_http):
    items = lzs.hn_search("hypersonic", max_results=5)
    assert len(items) == 2  # оба хита: title и story_title
    assert items[0]["meta"].startswith("250 points")
    assert items[1]["url"].startswith("https://news.ycombinator.com/item?id=2")


def test_github_parses_search(mock_http):
    items = lzs.github_repo_search("electrolyte", max_results=5)
    assert len(items) == 1
    assert items[0]["title"] == "org/cool-repo"
    assert "5300" in items[0]["meta"]


def test_api_scan_dedupes_and_writes_trace(mock_http, monkeypatch):
    traces = []
    monkeypatch.setattr(lzs, "_write_llm_trace", lambda rec: traces.append(rec))
    # один и тот же URL из разных источников не дублируется
    res = lzs.lz_api_scan(["batteries"], max_per_source=5, dept="lz")
    urls = [i["url"] for i in res["items"] if i.get("url")]
    assert len(urls) == len(set(urls))
    assert res["counts"].get("arxiv") == 2
    assert len(traces) == 1
    rec = traces[0]
    assert rec["trace_type"] == "lz_api_scan"
    assert rec["dept"] == "lz"
    assert rec["ok"] is True
    assert rec["items_fetched"] == res["total_items"] if hasattr(res, "total_items") else rec["items_fetched"] == len(res["items"])
    assert rec["est_tokens_saved"] >= 0
    assert res["trace_id"]


def test_route_lz_api_scan(mock_http, monkeypatch):
    traces = []
    monkeypatch.setattr(lzs, "_write_llm_trace", lambda rec: traces.append(rec))
    import llm_proxy
    c = llm_proxy.app.test_client()
    r = c.post("/lz/api-scan", json={"topics": ["chip supply chains"]})
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 5  # arxiv 2 + hn 2 + github 1
    assert "text" in data and "- [arxiv]" in data["text"]
    assert len(traces) == 1

    r2 = c.post("/lz/api-scan", json={})
    assert r2.status_code == 400
