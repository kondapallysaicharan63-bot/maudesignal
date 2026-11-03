"""PMS artefacts a person decides on: board, note to file, checklists, QMS export.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), added
2026-11-03 from reviewer feedback (PRD-19 to PRD-25).

Nothing in this package decides anything. A board status, a note-to-file decision and
every checklist answer are typed by a named person and written to the hash-chained audit
trail. The tool only prepares evidence; nothing is filed with FDA. This is not a QMS.
"""

from maudesignal.pms.asof import DELAY_SENTENCE, AsOf, as_of_text, stored_as_of
from maudesignal.pms.board import (
    STATUS_LABELS,
    STATUSES,
    BoardError,
    BoardRow,
    board_state,
    change_status,
)
from maudesignal.pms.checklists import (
    EvidencePack,
    escalation_checklist,
    recall_check,
    risk_section,
)
from maudesignal.pms.note_to_file import (
    DECISIONS,
    NOTE_LABEL,
    NoteToFile,
    NoteToFileError,
    record_note_to_file,
)

__all__ = [
    "DECISIONS",
    "DELAY_SENTENCE",
    "NOTE_LABEL",
    "STATUSES",
    "STATUS_LABELS",
    "AsOf",
    "BoardError",
    "BoardRow",
    "EvidencePack",
    "NoteToFile",
    "NoteToFileError",
    "as_of_text",
    "board_state",
    "change_status",
    "escalation_checklist",
    "recall_check",
    "record_note_to_file",
    "risk_section",
    "stored_as_of",
]
