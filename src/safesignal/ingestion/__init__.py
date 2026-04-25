"""MAUDE ingestion module (Feature F1).

Pulls adverse event reports from openFDA and stores them in the database.
"""

from safesignal.ingestion.openfda_client import OpenFDAClient
from safesignal.ingestion.pipeline import IngestionResult, ingest_product_code

__all__ = ["IngestionResult", "OpenFDAClient", "ingest_product_code"]
