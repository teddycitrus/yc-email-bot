import unicodedata


def normalize_name(name: str) -> str:
    name = name.lower()
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.encode("ascii", errors="ignore").decode("ascii")
    name = name.replace("'", "")
    return name.strip()
