"""Tiny Flask front-end for email-me.

A single page collects YC URLs / company domains (typed or via a .txt
upload) plus a per-target count, and streams per-email verification
results back as NDJSON so the UI can render them live without holding
a long-poll open.

Designed to run on a single small VM with outbound port 25 available
(e.g. Oracle Cloud Always Free) — see README for the deploy recipe.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterator

from flask import Flask, Response, render_template, request

from email_me.main import (
    augment_with_team,
    build_master_list,
    classify_target,
)
from email_me.models import (
    CompanyData,
    CompanyNotFoundError,
    ScrapingError,
    VerificationStatus,
)
from email_me.scraper import resolve_company_from_url, scrape_yc_page
from email_me.verifier import verify_email

# Hard caps to keep a single request from running forever or consuming
# unbounded memory. The site is unauthenticated by default; these are
# the only thing standing between it and abuse.
MAX_TARGETS_PER_REQUEST = 25
MAX_EMAILS_PER_TARGET = 20
MAX_UPLOAD_BYTES = 100_000

# Free serverless hosts (Render, HF Spaces, Vercel, etc.) all block outbound
# port 25, so the local SMTP probe just times out into UNKNOWN. Setting
# EMAIL_ME_DEFAULT_NO_SMTP=1 makes the UI default to permutation-only mode
# on those deploys, so users see fast useful output instead of UNKNOWN spam.
DEFAULT_NO_SMTP = os.environ.get("EMAIL_ME_DEFAULT_NO_SMTP", "0") == "1"


def _parse_targets(text: str, file_text: str) -> list[str]:
    """Pull one target per non-empty, non-comment line from both inputs."""
    targets: list[str] = []
    for blob in (text or "", file_text or ""):
        for line in blob.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                targets.append(line)
    # de-dupe while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def process_target(
    target: str,
    count: int,
    *,
    delay: float = 1.0,
    include_catch_all: bool = True,
    include_unknown: bool = False,
    scrape_team: bool = True,
    no_smtp: bool = False,
) -> Iterator[dict]:
    """Yield streaming events for one company target.

    Event shape: {"type": "start"|"company"|"result"|"done"|"error", ...}.
    Mirrors the CLI's run() flow but inverts control so the web layer
    can flush each event to the browser as it happens.
    """
    yield {"type": "start", "target": target}

    kind, value = classify_target(target)
    if kind == "invalid":
        yield {"type": "error", "target": target, "message": "Invalid target"}
        return

    try:
        if kind == "yc":
            company: CompanyData = scrape_yc_page(value, delay=delay)
        else:
            company = resolve_company_from_url(value, delay=delay)
    except (CompanyNotFoundError, ScrapingError) as e:
        yield {"type": "error", "target": target, "message": str(e)}
        return
    except Exception as e:
        yield {"type": "error", "target": target, "message": f"Network/scrape failure: {e}"}
        return

    if scrape_team:
        augment_with_team(company, delay=delay)

    yield {
        "type": "company",
        "target": target,
        "company": company.company_name,
        "domain": company.domain,
        "people": [
            {"name": f.full_name, "title": f.title} for f in company.founders
        ],
    }

    master_list = build_master_list(company)
    yield {"type": "permutations", "target": target, "total": len(master_list)}

    accept = {VerificationStatus.VERIFIED}
    if include_catch_all:
        accept.add(VerificationStatus.CATCH_ALL)
    if include_unknown:
        accept.add(VerificationStatus.UNKNOWN)

    if no_smtp:
        for email, name, role in master_list[:count]:
            yield {
                "type": "result",
                "target": target,
                "email": email,
                "role": role,
                "founder": name,
                "status": VerificationStatus.UNKNOWN.value,
                "accepted": True,
            }
        yield {"type": "done", "target": target, "found": min(count, len(master_list)), "probed": 0}
        return

    mx_cache: dict = {}
    found = 0
    probed = 0
    for email, name, role in master_list:
        if found >= count:
            break
        result = verify_email(email, mx_cache, delay=delay)
        result.founder_name = name
        result.role = role
        probed += 1
        accepted = result.status in accept
        if accepted:
            found += 1
        yield {
            "type": "result",
            "target": target,
            "email": email,
            "role": role,
            "founder": name,
            "status": result.status.value,
            "smtp_code": result.smtp_code,
            "latency_ms": result.latency_ms,
            "accepted": accepted,
        }

    yield {"type": "done", "target": target, "found": found, "probed": probed}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 16_384  # small headroom

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            max_targets=MAX_TARGETS_PER_REQUEST,
            max_count=MAX_EMAILS_PER_TARGET,
            default_no_smtp=DEFAULT_NO_SMTP,
        )

    @app.post("/process")
    def process() -> Response:
        text = request.form.get("targets", "")
        try:
            count = int(request.form.get("count", "2"))
        except ValueError:
            count = 2
        count = max(1, min(count, MAX_EMAILS_PER_TARGET))
        no_smtp = request.form.get("no_smtp", "0") == "1" or DEFAULT_NO_SMTP
        try:
            delay = float(request.form.get("delay", "1.0"))
        except ValueError:
            delay = 1.0
        delay = max(0.0, min(delay, 10.0))

        file_text = ""
        if "file" in request.files:
            f = request.files["file"]
            if f and f.filename:
                blob = f.read(MAX_UPLOAD_BYTES + 1)
                if len(blob) > MAX_UPLOAD_BYTES:
                    return Response(
                        json.dumps({"type": "error", "message": "file too large"}) + "\n",
                        status=413, mimetype="application/x-ndjson",
                    )
                try:
                    file_text = blob.decode("utf-8", errors="replace")
                except Exception:
                    file_text = ""

        targets = _parse_targets(text, file_text)
        if not targets:
            return Response(
                json.dumps({"type": "error", "message": "no targets provided"}) + "\n",
                status=400, mimetype="application/x-ndjson",
            )
        targets = targets[:MAX_TARGETS_PER_REQUEST]

        def stream() -> Iterator[bytes]:
            yield (json.dumps({"type": "batch_start", "total_targets": len(targets), "no_smtp": no_smtp}) + "\n").encode()
            for t in targets:
                for event in process_target(t, count, no_smtp=no_smtp, delay=delay):
                    yield (json.dumps(event) + "\n").encode()
            yield (json.dumps({"type": "batch_done"}) + "\n").encode()

        # X-Accel-Buffering disables nginx output buffering so events arrive
        # promptly when running behind a reverse proxy.
        return Response(
            stream(),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="email-me-web",
        description="Serve the email-me web front-end (dev server).",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    if args.host != "127.0.0.1" and not args.debug:
        print(
            f"[email-me-web] serving on {args.host}:{args.port}. "
            "Reminder: this app is unauthenticated — put it behind Caddy/"
            "Cloudflare/SSH-tunnel before exposing publicly.",
            file=sys.stderr,
        )
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    cli()
