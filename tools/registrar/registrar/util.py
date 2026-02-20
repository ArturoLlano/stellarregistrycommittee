from __future__ import annotations

import re
from datetime import datetime, timezone
import secrets
import string


ALPHANUM_UPPER = string.ascii_uppercase + string.digits


def safe_int(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    if not re.fullmatch(r"[0-9]+", s):
        return None
    try:
        return int(s)
    except Exception:
        return None


def iso_utc_now() -> str:
    # Match your example style: "...Z"
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def random_suffix(min_len: int = 6, max_len: int = 10) -> str:
    n = secrets.choice(range(min_len, max_len + 1))
    return "".join(secrets.choice(ALPHANUM_UPPER) for _ in range(n))
