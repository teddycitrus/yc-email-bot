import pytest
import responses as responses_lib

from email_me.main import ROLE_INBOXES, build_parser, classify_target, run
from email_me.models import VerificationStatus


@pytest.mark.parametrize(
    "raw,kind,value",
    [
        ("https://www.ycombinator.com/companies/stripe", "yc",
         "https://www.ycombinator.com/companies/stripe"),
        ("https://ycombinator.com/companies/stripe/", "yc",
         "https://ycombinator.com/companies/stripe/"),
        ("acme.com", "domain", "acme.com"),
        ("https://www.acme.com/team", "domain", "acme.com"),
        ("", "invalid", ""),
        ("not a url", "invalid", "not a url"),
    ],
)
def test_classify_target(raw, kind, value):
    assert classify_target(raw) == (kind, value)


@responses_lib.activate
def test_run_falls_back_to_role_inboxes():
    # No HTTP registered → homepage + team scrapes fail and are swallowed,
    # so no individuals are found and the role-inbox fallback kicks in.
    # --no-smtp keeps it offline (no DNS/SMTP).
    args = build_parser().parse_args(["acme.com", "3", "--no-smtp", "--delay", "0"])
    company, results, total = run(args)

    assert company.domain == "acme.com"
    assert total == len(ROLE_INBOXES)
    assert len(results) == 3
    assert [r.email for r in results] == [
        f"{local}@acme.com" for local in ROLE_INBOXES[:3]
    ]
    for r in results:
        assert r.role == "Role inbox"
        assert r.founder_name == ""
        assert r.status is VerificationStatus.UNKNOWN
