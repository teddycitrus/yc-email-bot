import argparse
import csv
import io
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from itertools import zip_longest

import requests

from email_me.models import (
    CompanyData,
    CompanyNotFoundError,
    ScrapingError,
    VerificationResult,
    VerificationStatus,
)
from email_me.permutations import generate_permutations
from email_me.scraper import (
    normalize_company_domain,
    resolve_company_from_url,
    scrape_team_members,
    scrape_yc_page,
)
from email_me.utils import normalize_name, resolve_role
from email_me.verifier import verify_email

YC_URL_RE = re.compile(
    r'^https?://(www\.)?ycombinator\.com/companies/[a-zA-Z0-9\-_]+/?$', re.I
)

# Common role inboxes to fall back to when no individuals can be discovered
# (e.g. an a16z portfolio company with no /team page). Ordered by how likely
# the address is a real, monitored inbox worth cold-outreaching.
ROLE_INBOXES = ("founders", "hello", "info", "contact", "team")


def classify_target(raw: str) -> tuple[str, str]:
    """Classify the positional target.

    Returns (kind, value): ('yc', url) for a YC company page,
    ('domain', domain) for any company website/domain, or
    ('invalid', raw) if neither.
    """
    raw = raw.strip()
    if YC_URL_RE.match(raw):
        return "yc", raw
    domain = normalize_company_domain(raw)
    if domain:
        return "domain", domain
    return "invalid", raw


def augment_with_team(company: CompanyData, delay: float) -> list:
    """Scrape the company's /team & /about pages and add anyone new in place.

    Best-effort: returns [] (and leaves `company` untouched) on any failure.
    Returns the list of newly added Founder objects so callers can log.
    """
    try:
        team = scrape_team_members(company.domain, delay=delay)
    except Exception:
        return []
    existing = {normalize_name(f.full_name) for f in company.founders}
    added = [t for t in team if normalize_name(t.full_name) not in existing]
    if added:
        company.founders.extend(added)
    return added


def build_master_list(company: CompanyData) -> list[tuple[str, str, str]]:
    """Produce the ordered (email, name, role) list to verify for a company.

    Permutations are interleaved across founders so each person gets a
    chance early. If no individuals are known for the domain, falls back
    to common role inboxes (founders@, hello@, info@, contact@, team@).
    """
    founder_count = len(company.founders)
    seen: set[str] = set()
    master_list: list[tuple[str, str, str]] = []

    if company.founders:
        per_founder = [
            [
                (email, founder.full_name, resolve_role(founder.title, founder_count))
                for email in generate_permutations(founder, company.domain)
            ]
            for founder in company.founders
        ]
        for round_entries in zip_longest(*per_founder):
            for entry in round_entries:
                if entry is None:
                    continue
                email, name, role = entry
                if email not in seen:
                    seen.add(email)
                    master_list.append((email, name, role))
        return master_list

    return [
        (f"{local}@{company.domain}", "", "Role inbox")
        for local in ROLE_INBOXES
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="email-me",
        description=(
            "Find and verify founder/contact email addresses for a company — "
            "from a YC company page or any company website/domain."
        ),
    )
    parser.add_argument(
        "target",
        help="YC company URL, or a company website/domain (e.g. acme.com)",
    )
    parser.add_argument("count", type=int, nargs="?", default=2, help="Number of verified emails to find (1-20, default: 2)")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table")
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--include-catch-all", action="store_true", default=True)
    parser.add_argument("--no-catch-all", dest="include_catch_all", action="store_false")
    parser.add_argument("--include-unknown", action="store_true")
    parser.add_argument("--team", dest="scrape_team", action="store_true", default=True,
                        help="Also scrape the company site for non-founder roles (default: on)")
    parser.add_argument("--no-team", dest="scrape_team", action="store_false",
                        help="Founders only; skip the company team/about page scrape")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-smtp", action="store_true")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if classify_target(args.target)[0] == "invalid":
        print(
            "Error: Invalid target. Pass a YC company URL "
            "(https://www.ycombinator.com/companies/<slug>) or a company "
            "website/domain (e.g. acme.com or https://acme.com)",
            file=sys.stderr,
        )
        sys.exit(3)
    if not (1 <= args.count <= 20):
        print("Error: count must be between 1 and 20", file=sys.stderr)
        sys.exit(3)


class _Progress:
    """In-place single-line status on stderr.

    ASCII-only (Windows cp1252 consoles choke on Unicode), and a no-op
    unless stderr is an interactive TTY — so pipes/redirects stay clean.
    """

    _FRAMES = "|/-\\"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._i = 0
        self._last_len = 0

    def update(self, msg: str) -> None:
        if not self.enabled:
            return
        frame = self._FRAMES[self._i % len(self._FRAMES)]
        self._i += 1
        width = shutil.get_terminal_size((80, 20)).columns
        line = f"{frame} {msg}"[: width - 1]
        pad = max(self._last_len - len(line), 0)
        sys.stderr.write("\r" + line + " " * pad)
        sys.stderr.flush()
        self._last_len = len(line)

    def done(self) -> None:
        if not self.enabled or self._last_len == 0:
            return
        sys.stderr.write("\r" + " " * self._last_len + "\r")
        sys.stderr.flush()
        self._last_len = 0


def run(args: argparse.Namespace) -> tuple[CompanyData, list[VerificationResult], int]:
    log = (lambda msg: print(msg, file=sys.stderr)) if args.verbose else (lambda _: None)
    progress = _Progress(enabled=sys.stderr.isatty() and not args.verbose)

    kind, target = classify_target(args.target)

    if kind == "yc":
        log(f"[INFO] Fetching {target}...")
        progress.update("Fetching YC company page...")
        try:
            company = scrape_yc_page(target, delay=args.delay)
        except requests.exceptions.ConnectionError:
            progress.done()
            print("Error: Could not reach ycombinator.com — check your network connection", file=sys.stderr)
            sys.exit(1)
        except CompanyNotFoundError as e:
            progress.done()
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except ScrapingError as e:
            progress.done()
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        log(
            f"[INFO] Found {len(company.founders)} founders: "
            + ", ".join(f.full_name for f in company.founders)
        )
    else:  # generic company website/domain (e.g. an a16z portfolio company)
        log(f"[INFO] Resolving company at {target}...")
        progress.update(f"Resolving {target}...")
        try:
            company = resolve_company_from_url(target, delay=args.delay)
        except ScrapingError as e:
            progress.done()
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        log(f"[INFO] Company: {company.company_name}")

    log(f"[INFO] Domain: {company.domain}")

    if args.scrape_team:
        progress.update(f"Scanning {company.domain} for non-founder contacts...")
        added = augment_with_team(company, delay=args.delay)
        if added:
            log(
                f"[TEAM] Found {len(added)} additional contact(s) from {company.domain}: "
                + ", ".join(f"{t.full_name} ({t.title})" for t in added)
            )
        else:
            log(f"[TEAM] No additional non-founder contacts found on {company.domain}")

    master_list = build_master_list(company)
    if company.founders:
        log(
            f"[INFO] Generated {len(master_list)} permutations across "
            f"{len(company.founders)} contact(s)"
        )
    else:
        log(
            f"[INFO] No individuals found for {company.domain}; falling back to "
            f"{len(master_list)} role-based inbox(es)"
        )

    if args.no_smtp:
        progress.done()
        results = [
            VerificationResult(email=e, founder_name=n, status=VerificationStatus.UNKNOWN, role=role)
            for e, n, role in master_list[: args.count]
        ]
        return company, results, len(master_list)

    mx_cache: dict = {}
    verified: list[VerificationResult] = []
    probed = 0

    accept_statuses = {VerificationStatus.VERIFIED}
    if args.include_catch_all:
        accept_statuses.add(VerificationStatus.CATCH_ALL)
    if args.include_unknown:
        accept_statuses.add(VerificationStatus.UNKNOWN)

    for email, founder_name, role in master_list:
        if len(verified) >= args.count:
            break
        progress.update(
            f"Verifying  [probed {probed} | found {len(verified)}/{args.count}]  {email}"
        )
        result = verify_email(email, mx_cache, delay=args.delay)
        result.founder_name = founder_name
        result.role = role
        probed += 1
        code_str = str(result.smtp_code) if result.smtp_code is not None else "-"
        log(f"[SMTP] {email} → {code_str} ({result.status.value.upper()}) [{result.latency_ms}ms]")
        if result.status in accept_statuses:
            verified.append(result)

    progress.done()
    return company, verified, probed


def format_table(company: CompanyData, results: list[VerificationResult], probed: int) -> str:
    col_email = max((len(r.email) for r in results), default=5)
    col_email = max(col_email, len("Email"))
    col_role = max((len(r.role) for r in results), default=4)
    col_role = max(col_role, len("Role"))
    col_founder = max((len(r.founder_name) for r in results), default=4)
    col_founder = max(col_founder, len("Name"))
    col_status = max((len(r.status.value) for r in results), default=6)
    col_status = max(col_status, len("Status"))

    sep = "━" * (4 + col_email + 3 + col_role + 3 + col_founder + 3 + col_status + 1)
    row_sep = (
        "─" * 3 + "┼" + "─" * (col_email + 2) + "┼" + "─" * (col_role + 2)
        + "┼" + "─" * (col_founder + 2) + "┼" + "─" * (col_status + 2)
    )

    header = (
        f" {'#':>2} │ {'Email':<{col_email}} │ {'Role':<{col_role}} │ {'Name':<{col_founder}} │ {'Status':<{col_status}}"
    )

    lines = [f"email-me results for {company.domain}", sep, header, row_sep]
    for i, r in enumerate(results, 1):
        lines.append(
            f" {i:>2} │ {r.email:<{col_email}} │ {r.role:<{col_role}} │ {r.founder_name:<{col_founder}} │ {r.status.value.upper():<{col_status}}"
        )
    lines.append(sep)
    lines.append("")
    found = len(results)
    lines.append(f"Found {found} verified email(s) out of {probed} permutations probed.")
    return "\n".join(lines)


def format_json(
    company: CompanyData,
    results: list[VerificationResult],
    probed: int,
    requested_count: int,
) -> str:
    payload = {
        "company": company.company_name,
        "domain": company.domain,
        "requested_count": requested_count,
        "results": [
            {
                "email": r.email,
                "role": r.role,
                "founder": r.founder_name,
                "status": r.status.value,
                "mx_host": r.mx_host,
                "smtp_code": r.smtp_code,
                "latency_ms": r.latency_ms,
            }
            for r in results
        ],
        "permutations_probed": probed,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(payload, indent=2)


def format_csv(results: list[VerificationResult]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["email", "role", "founder", "status", "mx_host", "smtp_code", "latency_ms"])
    for r in results:
        writer.writerow([r.email, r.role, r.founder_name, r.status.value, r.mx_host or "", r.smtp_code or "", r.latency_ms])
    return buf.getvalue().rstrip("\r\n")


def cli() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(args)
    company, results, probed = run(args)

    if args.format == "table":
        print(format_table(company, results, probed))
    elif args.format == "json":
        print(format_json(company, results, probed, args.count))
    elif args.format == "csv":
        print(format_csv(results))

    if not results:
        print(
            f"No verified email addresses found after probing {probed} permutations.",
            file=sys.stderr,
        )
    sys.exit(0 if results else 2)
