import re
import unicodedata


def normalize_name(name: str) -> str:
    name = name.lower()
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.encode("ascii", errors="ignore").decode("ascii")
    name = name.replace("'", "")
    return name.strip()


def resolve_role(title: str, founder_count: int) -> str:
    """Return the contact's role.

    Uses the title scraped from the YC page when available; otherwise
    falls back to an estimate (suffixed with "(est.)") based on how many
    founders the company has.
    """
    cleaned = re.sub(r"\s+", " ", (title or "").strip()).strip(" -/,|")
    if cleaned:
        return cleaned
    base = "Co-Founder" if founder_count > 1 else "Founder"
    return f"{base} (est.)"
