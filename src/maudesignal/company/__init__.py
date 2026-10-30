"""Simulated company for "Does this apply to us?" (HACKATHON-BUILT, Oct 26 – Nov 4, 2026).

SIMULATED company, REAL FDA evidence. The company (Demo MedTech Co.), its fictional
devices, owners and statuses are sample data in ``demo/company/``. The problem evidence
(MAUDE reports, recalls) is stored openFDA data. Statuses are set only by a named
simulated person and recorded in a hash-chained audit; the tool never sets one.
"""

from maudesignal.company.build import CompanyView, DeviceView, export_company, load_company
from maudesignal.company.checklist import CompanyChecklist, checklist_for
from maudesignal.company.constants import BANNER, COMPANY_NAME, STATUSES
from maudesignal.company.status import StatusError, append_status, verify_chain

__all__ = [
    "BANNER",
    "COMPANY_NAME",
    "STATUSES",
    "CompanyChecklist",
    "CompanyView",
    "DeviceView",
    "StatusError",
    "append_status",
    "checklist_for",
    "export_company",
    "load_company",
    "verify_chain",
]
