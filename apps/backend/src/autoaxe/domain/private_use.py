"""Single-user educational scope is distinct from redistribution to third parties.

Only protected session endpoints may consult this opt-in. Never use it to
authorize source fetching, storage, public API publication, or trading.
"""

import hmac
import os


def private_educational_read_enabled(subject_ref: str | None) -> bool:
    """Require explicit mode and an exact configured owner, not any login."""
    owner = os.getenv("AUTOAXE_PRIVATE_EDUCATIONAL_OWNER_SUBJECT_REF")
    return (
        os.getenv("AUTOAXE_PRIVATE_EDUCATIONAL_MODE") == "true"
        and bool(subject_ref)
        and bool(owner)
        and hmac.compare_digest(subject_ref or "", owner or "")
    )
