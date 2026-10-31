"""Self-hosted company audit mode: keep the question and answer text in the audit chain.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

By default (and always on the public demo) an ``ask`` audit entry keeps only the question's
SHA-256 and length. A company running its own copy can turn on full text so the entry also
keeps the question text and the answer's spoken text, for its own review.

Exact semantics (fail closed). A flag is "on" when its value is ``1``, ``true``, ``yes`` or
``on`` (any case, surrounding spaces ignored); anything else, including unset, is off.
Full text is on only when ALL of these hold:

* ``MAUDESIGNAL_AUDIT_FULL_TEXT`` is on;
* ``MAUDESIGNAL_SELF_HOSTED`` is on (an explicit second statement that this is a company's
  own deployment);
* no public signal is present: no demo key (``MAUDESIGNAL_DEMO_KEYS`` non-empty, or a demo key
  in the key store in use), ``MAUDESIGNAL_PUBLIC_DEMO`` not on, ``VERCEL_ENV`` not
  ``production``, and ``MAUDESIGNAL_WEB_ORIGINS`` empty or unset (and no web origin configured).

When full text was asked for but a condition fails, a warning
(``audit_full_text_refused``) names each failing condition (never a value) and the mode stays
off. Even when on, text that the patient-data guard flags is never stored: the entry keeps the
hash only and says the text was withheld. Only the key-authenticated ``ask`` tool (REST and
MCP) is affected; the website's live routes never store text.
"""

import os
from collections.abc import Mapping

from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

AUDIT_FULL_TEXT_ENV = "MAUDESIGNAL_AUDIT_FULL_TEXT"
SELF_HOSTED_ENV = "MAUDESIGNAL_SELF_HOSTED"
PUBLIC_DEMO_ENV = "MAUDESIGNAL_PUBLIC_DEMO"
DEMO_KEYS_ENV = "MAUDESIGNAL_DEMO_KEYS"  # same name as ``security.DEMO_KEYS_ENV``
WEB_ORIGINS_ENV = "MAUDESIGNAL_WEB_ORIGINS"  # same name as ``app.WEB_ORIGINS_ENV``
VERCEL_ENV = "VERCEL_ENV"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
#: Value of ``full_text`` in an entry whose text the patient-data guard kept out.
WITHHELD_PHI = "withheld_possible_patient_details"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def full_text_requested(env: Mapping[str, str] | None = None) -> bool:
    """True when ``MAUDESIGNAL_AUDIT_FULL_TEXT`` asks for full text (see the module text)."""
    src = os.environ if env is None else env
    return _truthy(src.get(AUDIT_FULL_TEXT_ENV))


def refusal_reasons(
    env: Mapping[str, str] | None = None,
    *,
    demo_keys: bool = False,
    web_origins: bool = False,
) -> list[str]:
    """Each condition that keeps full text off, by name only (empty when it may turn on).

    Args:
        env: Environment to read (default ``os.environ``).
        demo_keys: A public demo key is configured in the key store in use.
        web_origins: A web origin is configured for the app in use.
    """
    src = os.environ if env is None else env
    reasons: list[str] = []
    if not _truthy(src.get(SELF_HOSTED_ENV)):
        reasons.append(f"{SELF_HOSTED_ENV} is not on")
    if (src.get(DEMO_KEYS_ENV) or "").strip():
        reasons.append(f"{DEMO_KEYS_ENV} is set")
    if demo_keys:
        reasons.append("a public demo key is configured")
    if _truthy(src.get(PUBLIC_DEMO_ENV)):
        reasons.append(f"{PUBLIC_DEMO_ENV} is on")
    if (src.get(VERCEL_ENV) or "").strip().lower() == "production":
        reasons.append(f"{VERCEL_ENV} is production")
    if (src.get(WEB_ORIGINS_ENV) or "").strip() or web_origins:
        reasons.append(f"{WEB_ORIGINS_ENV} is set")
    return reasons


def resolve_full_text(
    requested: bool,
    env: Mapping[str, str] | None = None,
    *,
    demo_keys: bool = False,
    web_origins: bool = False,
) -> bool:
    """Whether full-text audit is on (fail closed; see the module text).

    Args:
        requested: Full text was asked for (env flag or an explicit setting).
        env: Environment to read (default ``os.environ``).
        demo_keys: A public demo key is configured in the key store in use.
        web_origins: A web origin is configured for the app in use.

    Returns:
        True only when requested and no refusal condition holds. Otherwise False, with a
        logged warning naming the conditions when it was requested.
    """
    if not requested:
        return False
    reasons = refusal_reasons(env, demo_keys=demo_keys, web_origins=web_origins)
    if reasons:
        logger.warning(
            "audit_full_text_refused",
            reasons=reasons,
            detail=f"{AUDIT_FULL_TEXT_ENV} is on but full text stays off; only hashes are stored.",
        )
        return False
    return True
