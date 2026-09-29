"""Serve the real dashboard against disposable, synthetic observability data."""

from evals.isolation import install


def main():
    root = install()
    import json
    from http.server import ThreadingHTTPServer
    from types import SimpleNamespace
    from unittest.mock import patch

    from evals.deterministic.test_compaction import SummaryClient, seed
    from evals.helpers import make_waku
    from waku.ops import dashboard

    app = make_waku(root / "preview", client=SummaryClient(), context_policy="compact", memory_policy="lifecycle",
                    retrieval_policy="selective", consolidate_every=10000)
    seed(app)
    app.compact()
    app.memory.facts.add("Alex", "Alex meets Tuesday at ten.")
    app.memory.retrieval.search("Alex", notify=app.tracer.event)
    app.tracer.event("context", {"stage": "dispatch", "model": "scripted-main", "session_id": "default",
                                "estimated_input_tokens": 5200, "input_budget_tokens": 23552, "capacity_source": "configured"})
    app.tracer.event("compaction_failed", {"session_id": "interrupted", "error": "Synthetic example"})
    (app.settings.home / "comparison_report.json").write_text(json.dumps({"experiment": "context-memory-v5",
        "status": "complete", "quality_status": "incomplete", "promotion_status": "incomplete", "trials": 5,
        "summary": {"arms": {a: {"complete": 180, "runs": 180, "critical_failures": []} for a in "ABCD"}}}), encoding="utf-8")
    info = {"model": "scripted-main", "providers": [], "provider": "anthropic", "pins": [], "graph_workflows": False}
    with patch.object(dashboard, "load_settings", return_value=app.settings), \
         patch.object(dashboard, "settings_info", return_value=info), \
         patch.object(dashboard, "list_providers", return_value=[]), \
         patch.object(dashboard, "list_connections", return_value=[]), \
         patch.object(dashboard, "tools_info", return_value={"catalog": [], "mcp": {"configured": False, "servers": [], "live": False}, "apple_on": False}), \
         patch.object(dashboard.browser_agent, "current", return_value=SimpleNamespace(session=app.session)):
        app.conn.close()
        server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
