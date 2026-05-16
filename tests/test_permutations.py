import re

import pytest

from email_me.models import Founder
from email_me.permutations import generate_permutations

EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def test_standard_founder():
    founder = Founder("Patrick", "Collison", "Patrick Collison", "Founder")
    result = generate_permutations(founder, "stripe.com")
    assert result[0] == "patrick@stripe.com"
    assert result[1] == "patrick.collison@stripe.com"
    assert result[2] == "p.collison@stripe.com"
    assert "collison@stripe.com" in result
    assert len(result) == 12


def test_accented_name():
    founder = Founder("François", "Dupré", "François Dupré", "Founder")
    result = generate_permutations(founder, "example.com")
    assert result[0] == "francois@example.com"
    assert "dupre@example.com" in result


def test_compound_last_name():
    founder = Founder("Jan", "Van Der Berg", "Jan Van Der Berg", "Founder")
    result = generate_permutations(founder, "example.com")
    assert "jan@example.com" in result
    assert "berg@example.com" in result
    assert "vanderberg@example.com" in result


def test_no_duplicates():
    founder = Founder("A", "B", "A B", "Founder")
    result = generate_permutations(founder, "x.com")
    assert len(result) == len(set(result))


def test_all_valid_format():
    founder = Founder("Jane", "Smith", "Jane Smith", "Founder")
    result = generate_permutations(founder, "startup.io")
    for email in result:
        assert EMAIL_RE.match(email), f"Invalid format: {email}"


def test_apostrophe_removed():
    founder = Founder("O'Brien", "Connor", "O'Brien Connor", "Founder")
    result = generate_permutations(founder, "example.com")
    for email in result:
        assert "'" not in email


def test_no_empty_strings():
    founder = Founder("Jane", "Smith", "Jane Smith", "Founder")
    result = generate_permutations(founder, "example.com")
    assert all(email for email in result)


def test_compound_no_duplicates():
    founder = Founder("Jan", "Van Der Berg", "Jan Van Der Berg", "Founder")
    result = generate_permutations(founder, "example.com")
    assert len(result) == len(set(result))
