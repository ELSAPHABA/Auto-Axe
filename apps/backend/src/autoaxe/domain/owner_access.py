"""Owner-only read authorization (independent of data redistribution rights).

This project is personal and non-commercial by design, not a selectable mode.
Only authenticated private BFF routes may use this owner check.
"""

import hmac
import os


def is_configured_owner(subject_ref: str | None) -> bool:
    """Grant private owner viewing only to a matching configured OIDC subject."""
    owner = os.getenv("AUTOAXE_OWNER_SUBJECT_REF")
    if not subject_ref or not owner:
        return False
    return hmac.compare_digest(subject_ref, owner)
