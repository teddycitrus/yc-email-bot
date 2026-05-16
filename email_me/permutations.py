from email_me.models import Founder
from email_me.utils import normalize_name


def generate_permutations(founder: Founder, domain: str) -> list[str]:
    f = normalize_name(founder.first_name)
    l = normalize_name(founder.last_name)

    fi = f[0] if f else ""
    li = l[0] if l else ""

    def make(local: str) -> str | None:
        if not local:
            return None
        return f"{local}@{domain}"

    patterns = [
        make(f),
        make(f"{f}.{l}"),
        make(f"{fi}.{l}"),
        make(f"{f}{l}"),
        make(f"{fi}{l}"),
        make(f"{f}_{l}"),
        make(f"{f}-{l}"),
        make(l),
        make(f"{l}.{f}"),
        make(f"{l}{f}"),
        make(fi),
        make(f"{fi}{li}"),
    ]

    seen = set()
    result = []
    for email in patterns:
        if email and email not in seen:
            seen.add(email)
            result.append(email)

    # Compound last name variants
    if " " in l:
        l_compact = l.replace(" ", "")
        l_token = l.rsplit(" ", 1)[-1]
        li_compact = l_compact[0] if l_compact else ""
        li_token = l_token[0] if l_token else ""

        for variant_l, variant_li in [(l_compact, li_compact), (l_token, li_token)]:
            compound_patterns = [
                make(f),
                make(f"{f}.{variant_l}"),
                make(f"{fi}.{variant_l}"),
                make(f"{f}{variant_l}"),
                make(f"{fi}{variant_l}"),
                make(f"{f}_{variant_l}"),
                make(f"{f}-{variant_l}"),
                make(variant_l),
                make(f"{variant_l}.{f}"),
                make(f"{variant_l}{f}"),
                make(fi),
                make(f"{fi}{variant_li}"),
            ]
            for email in compound_patterns:
                if email and email not in seen:
                    seen.add(email)
                    result.append(email)

    return result
