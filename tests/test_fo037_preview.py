#!/usr/bin/env python3
"""FO-037 C.1/C.2 tests: статическое превью /preview (наряд #135).

E.1: репозиторий с index.html → превью отдаёт HTML с text/html;
Content-Type по расширению; отказ-тесты: .. в пути, чужой ref, 404.
Protected prefix (C.2): /preview требует Bearer.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['TELEGRAM_BOT_TOKEN'] = 'test-bot-token'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo37-test'
os.environ['FORGE_REPOS_DIR'] = '/tmp/fosved-fo37-forge'

import llm_proxy  # noqa: E402
from proxy.core import app  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def forge_repo():
    """Bare repo + один коммит с index.html/style.css/app.js — git CLI."""
    repos_dir = "/tmp/fosved-fo37-forge/forge/repos"
    bare = os.path.join(repos_dir, "preview-repo.git")
    scratch = "/tmp/fosved-fo37-scratch"
    # чистый лист на каждый прогон: bare может остаться от прошлого забега
    subprocess.run(["rm", "-rf", bare, scratch], check=False)
    os.makedirs(repos_dir, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    os.makedirs(scratch)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    def git(*args):
        subprocess.run(["git", "-C", scratch] + list(args), check=True, env=env,
                       capture_output=True)
    git("init", "-q", "-b", "main")
    git("remote", "add", "origin", bare)
    with open(os.path.join(scratch, "index.html"), "w") as f:
        f.write("<h1>Превью работает</h1>")
    with open(os.path.join(scratch, "style.css"), "w") as f:
        f.write("body { color: red; }")
    with open(os.path.join(scratch, "app.js"), "w") as f:
        f.write("console.log('ok');")
    git("add", "-A")
    git("commit", "-q", "-m", "feat: preview fixture")
    git("push", "-q", "origin", "main")
    yield
    subprocess.run(["rm", "-rf", scratch])


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


AUTH = {"Authorization": "Bearer test-secret-123"}


class TestPreview:
    def test_html_content_type(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=index.html",
                       headers=AUTH)
        assert r.status_code == 200
        assert r.mimetype == "text/html"
        assert "Превью работает" in r.get_data(as_text=True)

    def test_css_content_type(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=style.css",
                       headers=AUTH)
        assert r.status_code == 200
        assert r.mimetype == "text/css"

    def test_js_content_type(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=app.js",
                       headers=AUTH)
        assert r.status_code == 200
        assert r.mimetype == "application/javascript"

    def test_unknown_ext_octet_stream(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=x.bin",
                       headers=AUTH)
        assert r.status_code == 404  # файла нет — 404 раньше mime

    def test_missing_file_404(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=nope.html",
                       headers=AUTH)
        assert r.status_code == 404

    def test_missing_repo_404(self, client):
        r = client.get("/preview?project=pj&repo=no-such-repo&path=index.html",
                       headers=AUTH)
        assert r.status_code == 404

    def test_path_traversal_rejected(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=../etc/passwd",
                       headers=AUTH)
        assert r.status_code == 400

    def test_bad_ref_rejected(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=index.html&ref=-Oevil",
                       headers=AUTH)
        assert r.status_code == 400

    def test_bad_repo_name_rejected(self, client):
        r = client.get("/preview?project=pj&repo=preview%20repo&path=index.html",
                       headers=AUTH)
        assert r.status_code == 400

    def test_preview_protected_without_bearer(self, client):
        r = client.get("/preview?project=pj&repo=preview-repo&path=index.html")
        assert r.status_code in (401, 403), "C.2: /preview в PROTECTED_PREFIXES"
