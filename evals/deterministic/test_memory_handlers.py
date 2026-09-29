"""Rendered memory buttons round-trip opaque IDs through HTML and JavaScript."""

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_memory_buttons_preserve_opaque_ids_after_html_parsing():
    class Buttons(HTMLParser):
        def __init__(self):
            super().__init__()
            self.handlers = []

        def handle_starttag(self, tag, attrs):
            if tag == "button" and "onclick" in dict(attrs):
                self.handlers.append(dict(attrs)["onclick"])

    root = Path(__file__).resolve().parents[2]
    source = "\n".join((root / "waku/ops/static/js" / name).read_text(encoding="utf-8")
                       for name in ("util.js", "ui.js", "views.js"))
    ids = [7, "0007", 'opaque-"quote\'']
    data = {"facts": [{"id": i, "subject": "project", "content": "value", "source": "user"} for i in ids],
            "episodes": [{"id": i, "summary": "event", "happened_at": "2026-01-01"} for i in ids]}
    rendered = subprocess.run([shutil.which("node"), "-"],
                              input=source + "\nconst d=" + json.dumps(data) + ";console.log(memSemantic(d)+memEpisodic(d));",
                              capture_output=True, text=True, encoding="utf-8", timeout=30, check=True).stdout
    parser = Buttons()
    parser.feed(rendered)
    execute = ("const calls=[];function editFact(id){calls.push(['edit',id])};"
               "function delMem(action,id){calls.push([action,id])};"
               + ";".join(parser.handlers) + ";console.log(JSON.stringify(calls));")
    result = subprocess.run([shutil.which("node"), "-e", execute], capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(result.stdout) == ([entry for i in ids for entry in (["edit", i], ["delete_fact", i])]
                                        + [["delete_episode", i] for i in ids])
