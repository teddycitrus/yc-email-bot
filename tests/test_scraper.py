import time

import pytest
import requests
import responses as responses_lib

from email_me.scraper import (
    _host_is_internal,
    _last_request_time,
    _safe_get,
    normalize_company_domain,
    resolve_company_from_url,
    scrape_yc_page,
)
from email_me.models import CompanyNotFoundError, ScrapingError

STRIPE_HTML = """
<html>
<head><title>Stripe - YC</title></head>
<body>
  <a href="https://stripe.com">stripe.com</a>
  <div>
    <h3>Active Founders</h3>
    <div>
      <h3>Patrick Collison</h3>
      <p>Founder/CEO</p>
    </div>
    <div>
      <h3>John Collison</h3>
      <p>Founder/President</p>
    </div>
  </div>
</body>
</html>
"""

SUBDOMAIN_HTML = """
<html>
<head><title>Acme - YC</title></head>
<body>
  <a href="https://docs.stripe.com/something">docs</a>
  <div>
    <h3>Active Founders</h3>
    <div>
      <h3>Alice Smith</h3>
      <p>Founder</p>
    </div>
  </div>
</body>
</html>
"""

SOCIAL_ONLY_HTML = """
<html>
<head><title>Socialco - YC</title></head>
<body>
  <a href="https://twitter.com/acme">Twitter</a>
  <a href="https://linkedin.com/company/acme">LinkedIn</a>
  <div>
    <h3>Active Founders</h3>
    <div>
      <h3>Bob Jones</h3>
      <p>Founder</p>
    </div>
  </div>
</body>
</html>
"""

NO_FOUNDERS_HTML = """
<html>
<head><title>Empty - YC</title></head>
<body>
  <a href="https://example.com">example</a>
  <div>
    <p>No founders here</p>
  </div>
</body>
</html>
"""


@responses_lib.activate
def test_scrape_stripe():
    responses_lib.add(
        responses_lib.GET,
        "https://www.ycombinator.com/companies/stripe",
        body=STRIPE_HTML,
        status=200,
    )
    data = scrape_yc_page("https://www.ycombinator.com/companies/stripe", delay=0)
    assert data.domain == "stripe.com"
    assert len(data.founders) == 2
    assert data.founders[0].first_name == "Patrick"
    assert data.founders[0].last_name == "Collison"
    assert data.founders[1].first_name == "John"


@responses_lib.activate
def test_404_raises():
    responses_lib.add(
        responses_lib.GET,
        "https://www.ycombinator.com/companies/doesnotexist",
        status=404,
    )
    with pytest.raises(CompanyNotFoundError):
        scrape_yc_page("https://www.ycombinator.com/companies/doesnotexist", delay=0)


@responses_lib.activate
def test_domain_extraction_from_subdomain():
    responses_lib.add(
        responses_lib.GET,
        "https://www.ycombinator.com/companies/acme",
        body=SUBDOMAIN_HTML,
        status=200,
    )
    data = scrape_yc_page("https://www.ycombinator.com/companies/acme", delay=0)
    assert data.domain == "stripe.com"


@responses_lib.activate
def test_social_links_excluded_raises_scraping_error():
    responses_lib.add(
        responses_lib.GET,
        "https://www.ycombinator.com/companies/socialco",
        body=SOCIAL_ONLY_HTML,
        status=200,
    )
    with pytest.raises(ScrapingError, match="Could not determine company domain"):
        scrape_yc_page("https://www.ycombinator.com/companies/socialco", delay=0)


@responses_lib.activate
def test_no_founders_raises_scraping_error():
    responses_lib.add(
        responses_lib.GET,
        "https://www.ycombinator.com/companies/empty",
        body=NO_FOUNDERS_HTML,
        status=200,
    )
    with pytest.raises(ScrapingError, match="No founders found"):
        scrape_yc_page("https://www.ycombinator.com/companies/empty", delay=0)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("acme.com", "acme.com"),
        ("https://acme.com", "acme.com"),
        ("https://www.acme.com/team", "acme.com"),
        ("HTTP://ACME.COM/about-us", "acme.com"),
        ("sub.acme.io", "acme.io"),
        ("https://u:p@acme.com:443/x", "acme.com"),
        ("", ""),
        ("not-a-domain", ""),
        ("localhost", ""),
        ("ftp://host", ""),
    ],
)
def test_normalize_company_domain(raw, expected):
    assert normalize_company_domain(raw) == expected


@responses_lib.activate
def test_resolve_company_from_url_reads_title():
    responses_lib.add(
        responses_lib.GET,
        "https://acme.com",
        body="<html><head><title>Acme Inc | Build faster</title></head></html>",
        status=200,
        content_type="text/html",
    )
    company = resolve_company_from_url("https://www.acme.com/pricing", delay=0)
    assert company.domain == "acme.com"
    assert company.company_name == "Acme Inc"
    assert company.founders == []


@responses_lib.activate
def test_resolve_company_from_url_survives_network_failure():
    # No responses registered → ConnectionError; resolver must swallow it
    # and still return a usable domain (name falls back to the domain).
    company = resolve_company_from_url("databricks.com", delay=0)
    assert company.domain == "databricks.com"
    assert company.company_name == "databricks.com"
    assert company.founders == []


def test_resolve_company_from_url_rejects_garbage():
    with pytest.raises(ScrapingError, match="Could not parse a company domain"):
        resolve_company_from_url("not-a-domain")


@responses_lib.activate
def test_founder_full_name_and_title():
    responses_lib.add(
        responses_lib.GET,
        "https://www.ycombinator.com/companies/stripe",
        body=STRIPE_HTML,
        status=200,
    )
    data = scrape_yc_page("https://www.ycombinator.com/companies/stripe", delay=0)
    assert data.founders[0].full_name == "Patrick Collison"
    assert "Founder" in data.founders[0].title


# ---------------------------------------------------------------------------
# Outbound hardening: SSRF guard, redirect control, rate limiting
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "host,internal",
    [
        ("acme.com", False),
        ("www.ycombinator.com", False),
        ("8.8.8.8", False),            # public IP literal — allowed
        ("localhost", True),
        ("metadata.google.internal", True),  # GCP metadata
        ("127.0.0.1", True),           # loopback
        ("169.254.169.254", True),     # AWS/GCP link-local metadata
        ("10.0.0.5", True),            # RFC1918
        ("192.168.1.10", True),
        ("172.16.4.4", True),
        ("::1", True),                 # IPv6 loopback
        ("api.dev.local", True),       # internal suffix
        ("svc.internal", True),
    ],
)
def test_host_is_internal(host, internal):
    assert _host_is_internal(host) is internal


def test_safe_get_rejects_non_web_scheme():
    with pytest.raises(requests.exceptions.RequestException):
        _safe_get("ftp://example.com/x", timeout=5, delay=0)


def test_safe_get_rejects_internal_host():
    with pytest.raises(requests.exceptions.RequestException):
        _safe_get("http://169.254.169.254/latest/meta-data/", timeout=5, delay=0)


@responses_lib.activate
def test_safe_get_follows_bounded_redirect_to_public_host():
    responses_lib.add(
        responses_lib.GET, "https://pub.example.com/",
        status=302, headers={"Location": "https://final.example.com/"},
    )
    responses_lib.add(
        responses_lib.GET, "https://final.example.com/",
        body="ok", status=200, content_type="text/html",
    )
    resp = _safe_get("https://pub.example.com/", timeout=5, delay=0)
    assert resp.status_code == 200
    assert resp.text == "ok"


@responses_lib.activate
def test_safe_get_blocks_redirect_to_internal_host():
    # A public site that 302s us at the cloud-metadata endpoint must be refused.
    responses_lib.add(
        responses_lib.GET, "https://pub.example.com/",
        status=302, headers={"Location": "http://169.254.169.254/"},
    )
    with pytest.raises(requests.exceptions.RequestException):
        _safe_get("https://pub.example.com/", timeout=5, delay=0)


@responses_lib.activate
def test_safe_get_caps_redirect_chain():
    responses_lib.add(
        responses_lib.GET, "https://loop.example.com/",
        status=302, headers={"Location": "https://loop.example.com/"},
    )
    with pytest.raises(requests.exceptions.TooManyRedirects):
        _safe_get("https://loop.example.com/", timeout=5, delay=0)


@responses_lib.activate
def test_safe_get_rate_limits_same_host():
    responses_lib.add(
        responses_lib.GET, "https://rl.example.com/",
        body="ok", status=200, content_type="text/html",
    )
    _last_request_time.pop("rl.example.com", None)
    start = time.monotonic()
    _safe_get("https://rl.example.com/", timeout=5, delay=0.15)
    _safe_get("https://rl.example.com/", timeout=5, delay=0.15)
    assert time.monotonic() - start >= 0.15
