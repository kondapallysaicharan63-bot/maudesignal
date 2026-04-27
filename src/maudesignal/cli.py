"""MaudeSignal command-line interface.

Entry point for the ``maudesignal`` command. Provides subcommands for
ingestion, extraction, dashboard launching, and reporting.

Run ``maudesignal --help`` for usage.
"""

from __future__ import annotations

import json
import sys

import typer
from rich.console import Console
from rich.table import Table

from maudesignal import __version__
from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.common.logging import configure_logging
from maudesignal.config import Config, ConfigError
from maudesignal.extraction.extractor import Extractor
from maudesignal.extraction.pipeline import extract_record
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.ingestion.pipeline import ingest_product_code
from maudesignal.storage.database import Database

app = typer.Typer(
    name="maudesignal",
    help="Open-source AI postmarket surveillance toolkit for FDA-cleared " "AI/ML medical devices.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


# ----------------------------------------------------------------------
# Global options
# ----------------------------------------------------------------------


@app.callback()
def _main(
    version: bool = typer.Option(False, "--version", help="Show MaudeSignal version and exit."),
) -> None:
    """MaudeSignal CLI root."""
    if version:
        console.print(f"maudesignal {__version__}")
        raise typer.Exit()


# ----------------------------------------------------------------------
# maudesignal ingest
# ----------------------------------------------------------------------


@app.command()
def ingest(
    product_code: str = typer.Option(
        ...,
        "--product-code",
        "-p",
        help="FDA 3-character product code (e.g., QIH, QAS, QFM).",
    ),
    start_date: str | None = typer.Option(
        None, "--start-date", help="Earliest date_received in YYYYMMDD format."
    ),
    end_date: str | None = typer.Option(
        None, "--end-date", help="Latest date_received in YYYYMMDD format."
    ),
    limit: int | None = typer.Option(
        None, "--limit", help="Maximum records to ingest (omit for all)."
    ),
) -> None:
    """Pull MAUDE adverse event reports from openFDA and store them locally.

    Examples:
        maudesignal ingest --product-code QIH --limit 5

        maudesignal ingest --product-code QIH --start-date 20250101 --end-date 20251231
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    _print_startup(config)

    db = Database(config.db_path)
    with OpenFDAClient(api_key=config.openfda_api_key) as client:
        try:
            result = ingest_product_code(
                client=client,
                db=db,
                product_code=product_code,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
        except MaudeSignalError as exc:
            console.print(f"[red]Ingestion failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    table = Table(title=f"Ingestion Summary — {result.product_code}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Records fetched", str(result.records_fetched))
    table.add_row("Records new", str(result.records_new))
    table.add_row("Records skipped", str(result.records_skipped))
    for reason, count in result.skip_reasons.items():
        table.add_row(f"  ...{reason}", str(count))
    console.print(table)


# ----------------------------------------------------------------------
# maudesignal extract
# ----------------------------------------------------------------------


@app.command()
def extract(
    product_code: str = typer.Option(
        ..., "--product-code", "-p", help="Only extract records for this code."
    ),
    limit: int = typer.Option(
        5,
        "--limit",
        help="Maximum records to extract in this run (default: 5). "
        "Start small to control API costs.",
    ),
) -> None:
    """Run Claude-based structured extraction on ingested MAUDE records.

    Requires ingestion to have been run first for the given product code.

    Example:
        maudesignal extract --product-code QIH --limit 3
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    _print_startup(config)

    db = Database(config.db_path)
    loader = SkillLoader(config.project_root / "skills")

    try:
        skill_extractor = loader.load("maude-narrative-extractor")
        skill_severity = loader.load("severity-triage")
        skill_classifier = loader.load("ai-failure-mode-classifier")
    except MaudeSignalError as exc:
        console.print(f"[red]Skill load failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]Loaded Skills:[/green] "
        f"{skill_extractor.name} v{skill_extractor.version}, "
        f"{skill_severity.name} v{skill_severity.version}, "
        f"{skill_classifier.name} v{skill_classifier.version}"
    )

    events = db.list_normalized_events(product_code=product_code, limit=limit)
    if not events:
        console.print(
            f"[yellow]No ingested events found for {product_code}. "
            f"Run `maudesignal ingest --product-code {product_code}` first.[/yellow]"
        )
        raise typer.Exit(code=1)

    extractor = Extractor(config=config, db=db)
    console.print(f"Extracting {len(events)} record(s) through 3-Skill chain...")

    extractor_successes = 0
    severity_successes = 0
    classifier_successes = 0
    classifier_skipped = 0
    skill_failures = 0

    for event in events:
        if not event.narrative and not event.mfr_narrative:
            continue
        record_result = extract_record(
            extractor=extractor,
            db=db,
            event=event,
            skill_extractor=skill_extractor,
            skill_severity=skill_severity,
            skill_classifier=skill_classifier,
        )
        if record_result.extractor_result is not None:
            extractor_successes += 1
        if record_result.severity_result is not None:
            severity_successes += 1
        if record_result.classifier_result is not None:
            classifier_successes += 1
        if record_result.classifier_skipped_reason is not None:
            classifier_skipped += 1
        skill_failures += len(record_result.errors)

    total_spend = db.total_llm_cost_usd()
    table = Table(title="Extraction Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Skill #1 (extractor) successes", str(extractor_successes))
    table.add_row("Skill #3 (severity) successes", str(severity_successes))
    table.add_row("Skill #4 (classifier) successes", str(classifier_successes))
    table.add_row("Skill #4 skipped (non-AI per extractor)", str(classifier_skipped))
    table.add_row("Skill failures (any Skill)", str(skill_failures))
    table.add_row("Cumulative LLM spend (USD)", f"${total_spend:.4f}")
    console.print(table)


# ----------------------------------------------------------------------
# maudesignal status
# ----------------------------------------------------------------------


@app.command()
def status() -> None:
    """Print current config, database contents, and LLM spend."""
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    db = Database(config.db_path)

    console.print("[bold]Configuration:[/bold]")
    console.print(json.dumps(config.masked_summary(), indent=2))

    console.print("\n[bold]Database:[/bold]")
    console.print(f"  Path: {db.path}")
    console.print(f"  Raw reports: {db.count_raw_reports()}")
    console.print(f"  Cumulative LLM spend: ${db.total_llm_cost_usd():.4f}")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _print_startup(config: Config) -> None:
    """Print a concise banner so the user sees which config is active."""
    if config.llm_provider == "groq":
        model = config.groq_model
    elif config.llm_provider == "anthropic":
        model = config.claude_model_extraction
    elif config.llm_provider == "gemini":
        model = config.gemini_model
    else:
        model = config.openai_model

    console.print(
        f"[dim]maudesignal {__version__} — "
        f"provider={config.llm_provider}, model={model} — "
        f"db={config.db_path.name}[/dim]"
    )


if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
