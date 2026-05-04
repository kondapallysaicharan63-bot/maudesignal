"""Phase 4: multi-source integration for MaudeSignal."""

from maudesignal.sources.clinicaltrials import ClinicalTrialsFetcher
from maudesignal.sources.pubmed import PubMedFetcher

__all__ = ["PubMedFetcher", "ClinicalTrialsFetcher"]
