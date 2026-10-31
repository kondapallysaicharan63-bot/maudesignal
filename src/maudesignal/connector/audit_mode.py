"""Self-hosted company audit mode: keep the question and answer text in the audit chain.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

By default (and always on the public demo) an ``ask`` audit entry keeps only the question's
SHA-256 and length. A company running its own copy can set ``MAUDESIGNAL_AUDIT_FULL_TEXT=1``
so the entry also keeps the question text and the answer's spoken text, for its own review.

Exact semantics:

* ``MAUDESIGNAL_AUDIT_FULL_TEXT``: ``1``, ``true``, ``yes`` or ``on`` (any case, surrounding
  spaces ignored) asks for full text. Anything else, including unset, empty, ``0`` and
  ``false``, leaves it off.
* The request is refused (a warning is logged and the mode stays off) when the deployment
  looks public: ``MAUDESIGNAL_DEMO_KEYS`` is non-empty, a public demo key is configured, or
  ``MAUDESIGNAL_PUBLIC_DEMO`` is ``1``/``true``/``yes``/``on``.
* Even when on, text that the patient-data guard flags is never stored: the entry keeps the
  hash only and says the text was withheld.
"""

import os
from collections.abc import Mapping

from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

AUDIT_FULL_TEXT_ENV = "MAUDESIGNAL_AUDIT_FULL_TEXT"
PUBLIC_DEMO_ENV = "MAUDESIGNAL_PUBLIC_DEMO"
DEMO_KEYS_ENV = "MAUDESIGNAL_DEMO_KEYS"  # same name as ``security.DEMO_KEYS_ENV``
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
#: Value of ``full_text`` in an entry whose text the patient-data guard kept out.
WITHHELD_PHI = "withheld_possible_patient_details"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def full_text_requested(env: Mapping[str, str] | None = None) -> bool:
    """True when ``MAUDESIGNAL_AUDIT_FULL_TEXT`` asks for full text (see the module text)."""
    src = os.environ if env is None else env
    return _truthy(src.get(AUDIT_FULL_TEXT_ENV))


def deployment_looks_public(env: Mapping[str, str] | None = None, demo_keys: bool = False) -> bool:
    """True when this deployment serves the public demo.

    Args:
        env: Environment to read (default ``os.environ``).
        demo_keys: A public demo key is configured in the key store in use.
    """
    src = os.environ if env is None else env
    return (
        demo_keys
        or bool((src.get(DEMO_KEYS_ENV) or "").strip())
        or _truthy(src.get(PUBLIC_DEMO_ENV))
    )


def resolve_full_text(
    requested: bool, env: Mapping[str, str] | None = None, demo_keys: bool = False
) -> bool:
    """Whether full-text audit is on: requested and the deployment is not public.

    Args:
        requested: Full text was asked for (env flag or an explicit setting).
        env: Environment to read (default ``os.environ``).
        demo_keys: A public demo key is configured in the key store in use.

    Returns:
        True only for a non-public deployment that asked for it. A public one that asked
        gets a logged warning and False.
    """
    if not requested:
        return False
    if deployment_looks_public(env, demo_keys):
        logger.warning(
            "audit_full_text_refused_public_demo",
            detail=(
                f"{AUDIT_FULL_TEXT_ENV} is set but this deployment looks public "
                f"({DEMO_KEYS_ENV} or {PUBLIC_DEMO_ENV}); only question hashes are stored."
            ),
        )
        return False
    return True
