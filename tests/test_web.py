import json

import pytest
import responses as responses_lib

pytest.importorskip("flask")

from email_me.web import _parse_targets, create_app, process_target  # noqa: E402


def test_parse_targets_dedupes_and_strips_comments():
    text = "  acme.com\n\nacme.com\n# a comment\nfoo.io"
    file_text = "foo.io\nbar.dev"
    assert _parse_targets(text, file_text) == ["acme.com", "foo.io", "bar.dev"]


def test_process_target_invalid_emits_error():
    events = list(process_target("garbage", count=2, delay=0))
    types = [e["type"] for e in events]
    assert "error" in types
    assert events[-1]["type"] == "error"


@responses_lib.activate
def test_process_target_no_smtp_streams_role_inboxes():
    # No HTTP registered → resolve & team scrapes fail and are swallowed →
    # no individuals → role-inbox fallback. no_smtp keeps it offline.
    events = list(process_target("acme.com", count=3, delay=0, no_smtp=True))
    types = [e["type"] for e in events]
    # Expect: start → company → permutations → 3 results → done
    assert types[0] == "start"
    assert "company" in types
    assert "permutations" in types
    assert types[-1] == "done"
    result_emails = [e["email"] for e in events if e["type"] == "result"]
    assert result_emails == [
        "founders@acme.com",
        "hello@acme.com",
        "info@acme.com",
    ]
    assert all(e["accepted"] for e in events if e["type"] == "result")


def test_index_route_renders():
    client = create_app().test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "email-me" in body
    assert "Targets" in body


def test_process_endpoint_rejects_empty_form():
    client = create_app().test_client()
    resp = client.post("/process", data={"targets": "", "count": "2"})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True).strip().splitlines()[0]
    assert json.loads(body)["type"] == "error"


@responses_lib.activate
def test_process_endpoint_streams_ndjson():
    client = create_app().test_client()
    resp = client.post("/process", data={"targets": "garbage-target", "count": "1", "delay": "0"})
    assert resp.status_code == 200
    assert resp.mimetype == "application/x-ndjson"
    lines = [
        json.loads(l) for l in resp.get_data(as_text=True).splitlines() if l.strip()
    ]
    types = [l["type"] for l in lines]
    assert types[0] == "batch_start"
    assert types[-1] == "batch_done"
    assert any(l["type"] == "error" for l in lines)


@responses_lib.activate
def test_process_endpoint_honors_no_smtp_form_flag():
    client = create_app().test_client()
    resp = client.post(
        "/process",
        data={"targets": "acme.com", "count": "2", "no_smtp": "1", "delay": "0"},
    )
    lines = [json.loads(l) for l in resp.get_data(as_text=True).splitlines() if l.strip()]
    assert lines[0]["type"] == "batch_start"
    assert lines[0]["no_smtp"] is True
    # In no_smtp mode every emitted result must be marked accepted (no real probing).
    results = [l for l in lines if l["type"] == "result"]
    assert results, "expected at least one result event"
    assert all(r["accepted"] is True for r in results)


@responses_lib.activate
def test_default_no_smtp_env_is_honored(monkeypatch):
    import email_me.web as web

    monkeypatch.setattr(web, "DEFAULT_NO_SMTP", True)
    client = web.create_app().test_client()

    # Index reflects the env-driven default in the banner.
    body = client.get("/").get_data(as_text=True)
    assert "Serverless deploy" in body

    # And the endpoint forces no_smtp=True even when the form omits the flag.
    resp = client.post("/process", data={"targets": "acme.com", "count": "1", "delay": "0"})
    lines = [json.loads(l) for l in resp.get_data(as_text=True).splitlines() if l.strip()]
    assert lines[0]["no_smtp"] is True
