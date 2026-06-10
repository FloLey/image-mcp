"""Email allow-list logic, kept free of fastmcp imports so it is unit-testable
with nothing but the standard library (the CI job only installs pytest)."""

from __future__ import annotations


def parse_allowed_emails(raw: str | None) -> frozenset[str]:
    """Parse a comma-separated allow-list into a normalized set of emails.

    Whitespace around entries is ignored, comparison is case-insensitive, and
    empty entries are dropped, so ``"a@x.com, B@y.com,,"`` is two emails.
    """
    if not raw:
        return frozenset()
    return frozenset(
        part.strip().lower() for part in raw.split(",") if part.strip()
    )


def is_allowed_email(email: object, allowed: frozenset[str]) -> bool:
    """True only when ``email`` is a non-empty string in the allow-list.

    Fails closed: a missing/empty claim or an empty allow-list always denies.
    """
    if not allowed:
        return False
    if not isinstance(email, str):
        return False
    return email.strip().lower() in allowed
