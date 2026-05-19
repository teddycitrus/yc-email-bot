import html as html_lib
import ipaddress
import json
import re
import time
from urllib.parse import urljoin, urlparse, urlsplit

import requests
from bs4 import BeautifulSoup

from .models import CompanyData, Founder, CompanyNotFoundError, ScrapingError
from .utils import normalize_name

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

_EXCLUDED_DOMAINS = {
    "ycombinator.com", "twitter.com", "x.com",
    "linkedin.com", "github.com", "facebook.com", "instagram.com",
}

# --- Outbound request hardening --------------------------------------------
#
# Every fetch in this module targets a URL/domain that ultimately comes from
# user input (a YC URL, an arbitrary company domain, or a redirect chosen by
# the scraped site). That makes the outbound side the real attack surface:
# SSRF into internal/cloud-metadata services, redirect-based pivots, oversized
# responses, and hammering a target host. _safe_get() is the single chokepoint
# all fetches go through so these controls can't be bypassed per call site.

_MAX_REDIRECTS = 3
_MAX_RESPONSE_BYTES = 5_000_000  # soft cap (~5 MB) on a scraped page
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
_INTERNAL_SUFFIXES = (".local", ".internal", ".localhost")

# Per-host timestamp of the last outbound request, for polite rate limiting.
_last_request_time: dict[str, float] = {}


def _host_is_internal(host: str) -> bool:
    """True if `host` should never be fetched (loopback/private/metadata).

    Literal-IP and well-known internal names are blocked outright. A public
    hostname that *resolves* to a private IP is NOT covered here (no DNS is
    done — that would make the unit suite hit the network); for a single-user
    CLI where the operator chooses the target, that residual DNS-rebinding
    risk is acceptable and documented rather than silently overclaimed.
    """
    h = (host or "").strip().strip(".").lower()
    if not h or h in _BLOCKED_HOSTNAMES or h.endswith(_INTERNAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False  # a normal hostname, not an IP literal
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _throttle(host: str, delay: float) -> None:
    """Space out requests to the same host by at least `delay` seconds."""
    if delay > 0:
        last = _last_request_time.get(host)
        if last is not None:
            wait = delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
    _last_request_time[host] = time.monotonic()


def _safe_get(url: str, *, timeout: int, delay: float) -> requests.Response:
    """GET with SSRF guards + per-host rate limiting.

    Refuses non-http(s) schemes and internal/loopback/metadata targets,
    follows redirects manually with a bounded count (re-validating the host
    on every hop so a public site can't bounce us to an internal address),
    and rejects oversized bodies. Anything refused is raised as a
    requests.exceptions.RequestException subclass so existing call-site
    handlers catch it the same way they already catch network errors.
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        if parts.scheme not in ("http", "https"):
            raise requests.exceptions.InvalidURL(
                f"refusing non-web scheme: {parts.scheme!r}"
            )
        host = parts.hostname or ""
        if _host_is_internal(host):
            raise requests.exceptions.InvalidURL(
                f"refusing internal/loopback host: {host!r}"
            )

        _throttle(host, delay)
        resp = requests.get(
            current, headers=HEADERS, timeout=timeout, allow_redirects=False
        )

        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("Location", "")
            resp.close()
            if not location:
                raise requests.exceptions.InvalidURL("redirect without Location")
            current = urljoin(current, location)
            continue

        declared = resp.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > _MAX_RESPONSE_BYTES:
            resp.close()
            raise requests.exceptions.RequestException("response exceeds size cap")
        if len(resp.content) > _MAX_RESPONSE_BYTES:
            raise requests.exceptions.RequestException("response exceeds size cap")
        return resp

    raise requests.exceptions.TooManyRedirects(
        f"exceeded {_MAX_REDIRECTS} redirects"
    )


def normalize_company_domain(raw: str) -> str:
    """Reduce any URL or bare host to a registrable domain.

    Accepts 'https://www.acme.com/team', 'acme.com', 'sub.acme.com',
    'https://u:p@acme.com:443/x', etc. Returns '' if nothing domain-like
    can be extracted. Same two-label heuristic as the YC path (no Public
    Suffix List), so multi-part TLDs like co.uk are out of scope.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = "https://" + raw
    netloc = urlparse(raw).netloc.lower()
    netloc = netloc.split("@")[-1].split(":")[0].removeprefix("www.")
    if not netloc or "." not in netloc:
        return ""
    parts = netloc.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else netloc


def _derive_domain(href: str) -> str:
    return normalize_company_domain(href)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.split()
    return parts[0], " ".join(parts[1:]) if len(parts) > 1 else parts[0]


def _parse_data_page(soup: BeautifulSoup) -> tuple[str, str, list[Founder]]:
    """Extract company data from the Inertia/data-page JSON attribute."""
    el = soup.find(attrs={"data-page": True})
    if not el:
        return "", "", []

    data = json.loads(html_lib.unescape(el["data-page"]))
    company = data.get("props", {}).get("company", {})

    company_name = company.get("name", "")
    website = company.get("website", "")
    domain = _derive_domain(website) if website else ""

    founders = []
    for f in company.get("founders", []):
        if not f.get("is_active", True):
            continue
        full_name = f.get("full_name", "").strip()
        if not full_name:
            continue
        first_name, last_name = _split_name(full_name)
        founders.append(Founder(
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            title=f.get("title", ""),
        ))

    return company_name, domain, founders


def _parse_html_fallback(soup: BeautifulSoup) -> tuple[str, str, list[Founder]]:
    """Fallback: parse static HTML for the 'Active Founders' section."""
    company_name = ""
    title_tag = soup.find("title")
    if title_tag:
        company_name = title_tag.get_text(strip=True).split(" - ")[0]

    founders: list[Founder] = []
    for tag in soup.find_all(string=lambda t: t and "Active Founders" in t):
        container = tag.find_parent()
        for _ in range(5):
            parent = container.find_parent()
            if parent is None:
                break
            container = parent
            if len(container.find_all(recursive=False)) > 1:
                break

        for h3 in container.find_all("h3"):
            text = h3.get_text(strip=True)
            if not text or text == "Active Founders":
                continue
            first_name, last_name = _split_name(text)
            title = ""
            parent_div = h3.find_parent()
            if parent_div:
                for p in parent_div.find_all(["p", "span", "div"]):
                    t = p.get_text(strip=True)
                    if t and t != text:
                        title = t
                        break
            founders.append(Founder(
                first_name=first_name,
                last_name=last_name,
                full_name=text,
                title=title,
            ))
        break

    domain = ""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        netloc = urlparse(href).netloc.lower().removeprefix("www.")
        if any(netloc == d or netloc.endswith("." + d) for d in _EXCLUDED_DOMAINS):
            continue
        parts = netloc.split(".")
        domain = ".".join(parts[-2:]) if len(parts) > 2 else netloc
        if domain:
            break

    return company_name, domain, founders


def scrape_yc_page(url: str, delay: float = 1.0) -> CompanyData:
    try:
        response = _safe_get(url, timeout=10, delay=delay)
    except requests.exceptions.RequestException:
        raise ScrapingError("Could not reach ycombinator.com — check your network connection")

    if response.status_code == 404:
        raise CompanyNotFoundError(f"No YC company found at: {url}")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    company_name, domain, founders = _parse_data_page(soup)
    if not founders:
        company_name, domain, founders = _parse_html_fallback(soup)

    if not founders:
        raise ScrapingError("No founders found — page structure may have changed")
    if not domain:
        raise ScrapingError("Could not determine company domain")

    return CompanyData(company_name=company_name, domain=domain, founders=founders)


def resolve_company_from_url(raw: str, timeout: int = 10, delay: float = 1.0) -> CompanyData:
    """Build CompanyData straight from a company website/domain.

    Used for non-YC companies (e.g. an a16z portfolio company), where no
    structured founder list exists. Founders are left empty here — people
    are discovered later via scrape_team_members(), with a role-inbox
    fallback if that finds nothing. Network failures fetching the homepage
    are swallowed (the domain is still usable); only an unparseable target
    raises.
    """
    domain = normalize_company_domain(raw)
    if not domain:
        raise ScrapingError(f"Could not parse a company domain from: {raw!r}")

    company_name = domain
    for url in (f"https://{domain}", f"https://www.{domain}"):
        try:
            resp = _safe_get(url, timeout=timeout, delay=delay)
        except requests.exceptions.RequestException:
            continue
        if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", ""):
            continue
        try:
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            break
        title = soup.find("title")
        if title:
            # Trim common "Name | Tagline" / "Name - Tagline" suffixes.
            name = re.split(r"\s[|\-–—:·]\s", title.get_text(strip=True))[0].strip()
            if name:
                company_name = name
        break

    return CompanyData(company_name=company_name, domain=domain, founders=[])


# --- Best-effort non-founder discovery (company /team, /about, ...) ---------
#
# A YC page only lists founders. To surface engineers, non-founder CTOs, etc.
# we additionally probe the company's own site. Every site's markup differs,
# so this is heuristic by nature: it never raises and returns [] on any miss.

_TEAM_PATHS = ("/team", "/about", "/about-us", "/company", "/people", "/our-team")

_ROLE_RE = re.compile(
    r"\b("
    r"co[- ]?founder|founder|"
    r"c[a-z]o\b|chief\s+[a-z]+\s+officer|"
    r"vp\b|vice\s+president|head\s+of|director|principal|"
    r"staff|senior|lead|"
    r"software\s+engineer|engineer|developer|programmer|"
    r"designer|product\s+manager|product\s+lead|"
    r"data\s+scientist|researcher|architect"
    r")\b",
    re.IGNORECASE,
)

# 2–4 capitalised tokens — a plausible person name, not a heading/CTA.
_NAME_RE = re.compile(r"^[A-Z][a-zA-Z'’\-]+(?:\s+[A-Z][a-zA-Z'’\-]+){1,3}$")
_BAD_NAME_WORDS = {
    "team", "about", "careers", "join", "company", "our", "the",
    "meet", "leadership", "contact", "home", "blog", "privacy",
}
_MAX_TEAM_CONTACTS = 30


def _looks_like_name(text: str) -> bool:
    text = text.strip()
    if not (3 <= len(text) <= 60) or not _NAME_RE.match(text):
        return False
    return not any(w in text.lower().split() for w in _BAD_NAME_WORDS)


def _clean_role(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -–—|,/·•\t")[:60]


def _extract_team_contacts(soup: BeautifulSoup) -> list[Founder]:
    """Pair role-bearing text nodes with a nearby person name."""
    contacts: list[Founder] = []
    seen: set[str] = set()

    for node in soup.find_all(string=_ROLE_RE.search):
        raw = str(node).strip()
        if not raw or len(raw) > 80:  # a real title is short
            continue
        role = _clean_role(raw)
        if not role:
            continue

        name = None
        scope = node.find_parent()
        for _ in range(3):  # walk up a few ancestors looking for a name
            if scope is None:
                break
            for el in scope.find_all(string=True):
                cand = str(el).strip()
                if cand != raw and _looks_like_name(cand):
                    name = cand
                    break
            if name:
                break
            scope = scope.find_parent()
        if not name:
            continue

        key = normalize_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        first, last = _split_name(name)
        contacts.append(Founder(first_name=first, last_name=last, full_name=name, title=role))
        if len(contacts) >= _MAX_TEAM_CONTACTS:
            break

    return contacts


def scrape_team_members(
    domain: str, timeout: int = 8, max_pages: int = 5, delay: float = 1.0
) -> list[Founder]:
    """Best-effort (name, role) people from a company's team/about page.

    Never raises — returns [] on any network/parse failure. Stops early once
    a page yields contacts to bound latency.
    """
    contacts: list[Founder] = []
    seen: set[str] = set()
    tried = 0

    for host in (f"https://{domain}", f"https://www.{domain}"):
        for path in _TEAM_PATHS:
            if tried >= max_pages or len(contacts) >= _MAX_TEAM_CONTACTS:
                return contacts[:_MAX_TEAM_CONTACTS]
            tried += 1
            try:
                resp = _safe_get(urljoin(host, path), timeout=timeout, delay=delay)
            except requests.exceptions.RequestException:
                continue
            if resp.status_code != 200:
                continue
            if "html" not in resp.headers.get("Content-Type", ""):
                continue
            try:
                soup = BeautifulSoup(resp.text, "lxml")
            except Exception:
                continue
            for c in _extract_team_contacts(soup):
                k = normalize_name(c.full_name)
                if k and k not in seen:
                    seen.add(k)
                    contacts.append(c)
        if contacts:  # got something from this host; don't hammer the next
            break

    return contacts[:_MAX_TEAM_CONTACTS]
