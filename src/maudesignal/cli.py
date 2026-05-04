"""MaudeSignal command-line interface.

Entry point for the ``maudesignal`` command. Provides subcommands for
ingestion, extraction, dashboard launching, and reporting.

Run ``maudesignal --help`` for usage.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table

from maudesignal import __version__
from maudesignal.alerting.checker import AlertChecker
from maudesignal.alerting.rules import VALID_DELIVERY, VALID_METRICS
from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.common.logging import configure_logging
from maudesignal.config import Config, ConfigError
from maudesignal.drift.interpreter import build_runtime, interpret_drift
from maudesignal.extraction.extractor import Extractor
from maudesignal.extraction.pipeline import extract_record
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.forecasting.trend_detector import VALID_METRICS as TREND_METRICS
from maudesignal.forecasting.trend_detector import TrendDetector
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.ingestion.pipeline import ingest_product_code
from maudesignal.report.psur_generator import PsurGenerator
from maudesignal.sources.clinicaltrials import ClinicalTrialsFetcher
from maudesignal.sources.pubmed import PubMedFetcher
from maudesignal.storage.database import Database

app = typer.Typer(
    name="maudesignal",
    help="Open-source AI postmarket surveillance toolkit for FDA-cleared " "AI/ML medical devices.",
    add_completion=False,
    no_args_is_help=True,
)
catalog_app = typer.Typer(
    name="catalog",
    help="Manage the FDA AI/ML device catalog.",
    no_args_is_help=True,
)
analyze_app = typer.Typer(
    name="analyze",
    help="Phase 2: root-cause analysis commands.",
    no_args_is_help=True,
)
alert_app = typer.Typer(
    name="alert",
    help="Phase 2: configure and check alert rules.",
    no_args_is_help=True,
)
forecast_app = typer.Typer(
    name="forecast",
    help="Phase 3: trend detection and forecasting.",
    no_args_is_help=True,
)
sources_app = typer.Typer(
    name="sources",
    help="Phase 4: fetch external publications and trials.",
    no_args_is_help=True,
)
psur_app = typer.Typer(
    name="psur",
    help="Phase 5: automated PSUR regulatory response generation.",
    no_args_is_help=True,
)
app.add_typer(catalog_app, name="catalog")
app.add_typer(analyze_app, name="analyze")
app.add_typer(alert_app, name="alert")
app.add_typer(forecast_app, name="forecast")
app.add_typer(sources_app, name="sources")
app.add_typer(psur_app, name="psur")
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
    product_code: str | None = typer.Option(
        None,
        "--product-code",
        "-p",
        help="FDA 3-character product code (e.g., QIH, QAS, QFM).",
    ),
    all_ai: bool = typer.Option(
        False,
        "--all-ai",
        help="Ingest MAUDE records for every product code in the AI/ML catalog.",
    ),
    start_date: str | None = typer.Option(
        None, "--start-date", help="Earliest date_received in YYYYMMDD format."
    ),
    end_date: str | None = typer.Option(
        None, "--end-date", help="Latest date_received in YYYYMMDD format."
    ),
    limit: int | None = typer.Option(
        None, "--limit", help="Maximum records per product code (omit for all)."
    ),
) -> None:
    """Pull MAUDE adverse event reports from openFDA and store them locally.

    Examples:
        maudesignal ingest --product-code QIH --limit 5

        maudesignal ingest --all-ai --limit 20

        maudesignal ingest --product-code QIH --start-date 20250101 --end-date 20251231
    """
    if not product_code and not all_ai:
        console.print("[red]Error:[/red] Provide --product-code or --all-ai.")
        raise typer.Exit(code=2)

    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    _print_startup(config)

    db = Database(config.db_path)

    if all_ai:
        _ingest_all_catalog(db, config, start_date=start_date, end_date=end_date, limit=limit)
        return

    assert product_code is not None  # narrowing — guarded above
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


def _ingest_all_catalog(
    db: Database,
    config: Config,
    *,
    start_date: str | None,
    end_date: str | None,
    limit: int | None,
) -> None:
    """Ingest MAUDE records for every product code stored in the catalog."""
    devices = db.list_catalog_devices()
    if not devices:
        console.print("[yellow]Catalog is empty. Run `maudesignal catalog update` first.[/yellow]")
        return

    console.print(f"[green]Bulk ingesting {len(devices)} catalog product codes...[/green]")
    total_fetched = total_new = 0
    errors: list[str] = []

    with OpenFDAClient(api_key=config.openfda_api_key) as client:
        for device in devices:
            try:
                result = ingest_product_code(
                    client=client,
                    db=db,
                    product_code=device.product_code,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                )
                total_fetched += result.records_fetched
                total_new += result.records_new
                if result.records_fetched:
                    console.print(
                        f"  [dim]{device.product_code}[/dim] "
                        f"fetched={result.records_fetched} new={result.records_new}"
                    )
            except MaudeSignalError as exc:
                msg = f"{device.product_code}: {exc}"
                errors.append(msg)
                console.print(f"  [yellow]skip {device.product_code} — {exc}[/yellow]")

    table = Table(title="Bulk Ingest Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Product codes attempted", str(len(devices)))
    table.add_row("Total records fetched", str(total_fetched))
    table.add_row("Total records new", str(total_new))
    table.add_row("Errors", str(len(errors)))
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
def drift(
    product_code: str = typer.Option(..., "--product-code", "-p"),
    baseline_window: int = typer.Option(30, "--baseline-window"),
    current_window: int = typer.Option(7, "--current-window"),
    metric: str = typer.Option("confidence_score", "--metric"),
) -> None:
    """Compute drift on extracted records and run Skill #5 interpretation."""
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    _print_startup(config)
    extractor, db, skills_root = build_runtime(config)

    rows = db.list_extractions(product_code=product_code, skill_name="maude-narrative-extractor")
    if not rows:
        console.print(f"[yellow]No extractions found for product_code={product_code}.[/yellow]")
        raise typer.Exit(code=1)

    now = datetime.now(UTC)
    cur_start = now - timedelta(days=current_window)
    base_start = cur_start - timedelta(days=baseline_window)

    def _ts(r: object) -> datetime:
        ts: datetime = r.extraction_ts  # type: ignore[attr-defined]
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)

    baseline = [getattr(r, metric) for r in rows if base_start <= _ts(r) < cur_start]
    current = [getattr(r, metric) for r in rows if _ts(r) >= cur_start]

    if len(baseline) < 2 or len(current) < 2:
        # Fallback: split all rows in half by index for MVP demos with sparse data.
        half = len(rows) // 2 or 1
        baseline = [getattr(r, metric) for r in rows[:half]]
        current = [getattr(r, metric) for r in rows[half:]]
        console.print(
            f"[yellow]Insufficient data in time windows; falling back to "
            f"index-split (n_baseline={len(baseline)}, n_current={len(current)}).[/yellow]"
        )

    try:
        result = interpret_drift(
            metric_name=metric,
            baseline_values=baseline,
            current_values=current,
            cohort_label=f"{product_code} {metric} drift run",
            extractor=extractor,
            skills_root=skills_root,
        )
    except MaudeSignalError as exc:
        console.print(f"[red]Drift interpretation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title=f"Drift verdict — {product_code}")
    table.add_column("Field")
    table.add_column("Value")
    for k in (
        "verdict",
        "headline",
        "recommended_action",
        "confidence_score",
        "requires_human_review",
    ):
        if k in result:
            table.add_row(k, str(result[k]))
    console.print(table)
    console.print("\n[dim]Full output:[/dim]")
    console.print(json.dumps(result, indent=2, default=str))


@app.command()
def report(
    product_code: str = typer.Option(
        ...,
        "--product-code",
        "-p",
        help="FDA 3-character product code (e.g. QIH).",
    ),
    start: str = typer.Option(
        ...,
        "--start",
        help="Start of extraction window, YYYY-MM-DD (inclusive).",
    ),
    end: str = typer.Option(
        ...,
        "--end",
        help="End of extraction window, YYYY-MM-DD (inclusive).",
    ),
    output_dir: str = typer.Option(
        "reports",
        "--output-dir",
        help="Directory to write report files (created if absent).",
    ),
) -> None:
    """Generate a PSUR-style periodic safety report from extraction data.

    Example:
        maudesignal report --product-code QIH --start 2025-01-01 --end 2025-12-31
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    db = Database(config.db_path)

    from maudesignal.report.generator import PSURGenerator

    generator = PSURGenerator(db)

    try:
        result = generator.generate(
            product_code=product_code,
            start_date=start,
            end_date=end,
            output_dir=output_dir,
        )
    except ValueError as exc:
        console.print(f"[red]Report generation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title=f"PSUR — {product_code}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Records in report", str(result["record_count"]))
    table.add_row("AI-related events", str(result["ai_related_count"]))
    table.add_row("Markdown", result["markdown_path"])
    if result.get("pdf_path"):
        table.add_row("PDF", result["pdf_path"])
    else:
        table.add_row("PDF", "[dim]skipped (weasyprint not installed)[/dim]")
    console.print(table)


# ----------------------------------------------------------------------
# maudesignal catalog
# ----------------------------------------------------------------------


@catalog_app.command("update")
def catalog_update(
    api_key: str | None = typer.Option(
        None, "--api-key", help="openFDA API key (optional — improves rate limit)."
    ),
) -> None:
    """Discover and store all FDA-cleared AI/ML device product codes.

    Queries the openFDA 510k API with a battery of AI/ML keyword searches
    and upserts results into the local device_catalog table.

    Example:
        maudesignal catalog update
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    db = Database(config.db_path)

    from maudesignal.catalog.fetcher import CatalogFetcher

    key = api_key or config.openfda_api_key
    fetcher = CatalogFetcher(db, api_key=key)
    console.print("[green]Scanning openFDA 510k API for AI/ML devices...[/green]")
    result = fetcher.update()

    table = Table(title="Catalog Update Summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Keywords searched", str(result.keywords_searched))
    table.add_row("Unique devices found", str(result.devices_found))
    table.add_row("Product codes new", str(result.product_codes_new))
    table.add_row("Product codes updated", str(result.product_codes_updated))
    table.add_row("Errors", str(len(result.errors)))
    console.print(table)

    if result.errors:
        console.print("[yellow]Errors:[/yellow]")
        for err in result.errors:
            console.print(f"  {err}")


@catalog_app.command("list")
def catalog_list(
    limit: int = typer.Option(50, "--limit", help="Maximum rows to display."),
) -> None:
    """List all device product codes in the local catalog.

    Example:
        maudesignal catalog list
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    db = Database(config.db_path)
    devices = db.list_catalog_devices()

    if not devices:
        console.print("[yellow]Catalog is empty. Run `maudesignal catalog update` first.[/yellow]")
        return

    table = Table(title=f"AI/ML Device Catalog ({len(devices)} product codes)")
    table.add_column("Code", style="bold cyan")
    table.add_column("Device Name")
    table.add_column("Company")
    table.add_column("Specialty")
    table.add_column("Source")

    for device in devices[:limit]:
        table.add_row(
            device.product_code,
            (device.device_name or "")[:50],
            (device.company_name or "")[:30],
            (device.specialty or "")[:25],
            device.source_keyword or "",
        )

    if len(devices) > limit:
        console.print(f"[dim]... and {len(devices) - limit} more. Use --limit to see more.[/dim]")
    console.print(table)


# ----------------------------------------------------------------------
# maudesignal analyze
# ----------------------------------------------------------------------


@analyze_app.command("root-cause")
def analyze_root_cause(
    product_code: str = typer.Option(..., "--product-code", "-p", help="FDA product code."),
    min_cluster: int = typer.Option(
        3, "--min-cluster", help="Minimum extractions per failure-mode cluster to analyze."
    ),
    device_name: str = typer.Option(
        "", "--device-name", help="Device brand name (cosmetic, used in LLM prompt)."
    ),
) -> None:
    """Run root-cause analysis on all failure-mode clusters for a product code.

    Requires that `extract` has already been run so classifier extractions exist.

    Example:
        maudesignal analyze root-cause --product-code QIH
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    db = Database(config.db_path)
    _print_startup(config)

    from maudesignal.analysis.root_cause import RootCauseAnalyzer

    extractor = Extractor(config=config, db=db)
    analyzer = RootCauseAnalyzer(
        extractor=extractor,
        db=db,
        skills_root=config.project_root / "skills",
    )

    console.print(
        f"[green]Running root-cause analysis for {product_code} "
        f"(min_cluster={min_cluster})...[/green]"
    )
    try:
        runs = analyzer.run(
            product_code=product_code,
            device_name=device_name,
            min_cluster_size=min_cluster,
        )
    except MaudeSignalError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not runs:
        console.print(
            f"[yellow]No clusters found for {product_code} with "
            f"min_cluster_size={min_cluster}. "
            "Run `extract` first or lower --min-cluster.[/yellow]"
        )
        return

    table = Table(title=f"Root Cause Analysis — {product_code}")
    table.add_column("Failure Mode", style="cyan")
    table.add_column("Cluster", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("Review?")
    table.add_column("Hypothesis (truncated)")

    for run in runs:
        out = run.output
        hypothesis = (out.get("root_cause_hypothesis") or "")[:70]
        review = "[yellow]YES[/yellow]" if out.get("requires_human_review") else "[green]no[/green]"
        table.add_row(
            run.cluster.failure_mode_category,
            str(run.cluster.cluster_size),
            f"{out.get('confidence_score', 0.0):.2f}",
            review,
            hypothesis,
        )

    console.print(table)
    console.print(f"\n[dim]{len(runs)} cluster(s) analyzed. Results saved to DB.[/dim]")


# ----------------------------------------------------------------------
# maudesignal alert
# ----------------------------------------------------------------------


@alert_app.command("add")
def alert_add(
    metric: str = typer.Option(
        ...,
        "--metric",
        "-m",
        help=f"Metric to monitor. One of: {', '.join(sorted(VALID_METRICS))}",
    ),
    threshold: float = typer.Option(
        ..., "--threshold", "-t", help="Alert fires when metric >= threshold."
    ),
    window: int = typer.Option(30, "--window", help="Look-back window in days."),
    delivery: str = typer.Option(
        "console",
        "--delivery",
        "-d",
        help=f"Delivery channel. One of: {', '.join(sorted(VALID_DELIVERY))}",
    ),
    product_code: str | None = typer.Option(
        None, "--product-code", "-p", help="Scope to one product code (omit for all)."
    ),
    webhook_url: str | None = typer.Option(
        None, "--webhook-url", help="Slack webhook URL (required when --delivery=slack)."
    ),
    email_to: str | None = typer.Option(
        None, "--email-to", help="Recipient email (required when --delivery=email)."
    ),
    smtp_host: str = typer.Option("smtp.gmail.com", "--smtp-host"),
    smtp_port: int = typer.Option(465, "--smtp-port"),
    email_from: str | None = typer.Option(None, "--email-from"),
    smtp_user: str | None = typer.Option(None, "--smtp-user"),
    smtp_pass: str | None = typer.Option(None, "--smtp-pass"),
    description: str | None = typer.Option(None, "--description", help="Human-readable note."),
) -> None:
    r"""Add a new alert rule.

    Examples:
        maudesignal alert add --metric ai_rate --threshold 0.6 --window 30
        maudesignal alert add --metric new_reports --threshold 10 --window 7 \
            --delivery slack --webhook-url https://hooks.slack.com/...
    """
    import uuid as _uuid

    if metric not in VALID_METRICS:
        console.print(f"[red]Unknown metric {metric!r}. Choose from: {sorted(VALID_METRICS)}[/red]")
        raise typer.Exit(code=2)
    if delivery not in VALID_DELIVERY:
        console.print(
            f"[red]Unknown delivery {delivery!r}. Choose from: {sorted(VALID_DELIVERY)}[/red]"
        )
        raise typer.Exit(code=2)
    if delivery == "slack" and not webhook_url:
        console.print("[red]--webhook-url is required when --delivery=slack[/red]")
        raise typer.Exit(code=2)
    if delivery == "email" and not email_to:
        console.print("[red]--email-to is required when --delivery=email[/red]")
        raise typer.Exit(code=2)

    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    db = Database(config.db_path)
    rule_id = str(_uuid.uuid4())[:8]

    delivery_cfg: dict[str, str] | None = None
    if delivery == "slack" and webhook_url:
        delivery_cfg = {"webhook_url": webhook_url}
    elif delivery == "email" and email_to:
        delivery_cfg = {
            "recipient": email_to,
            "sender": email_from or "maudesignal@localhost",
            "smtp_host": smtp_host,
            "smtp_port": str(smtp_port),
        }
        if smtp_user:
            delivery_cfg["username"] = smtp_user
        if smtp_pass:
            delivery_cfg["password"] = smtp_pass

    db.insert_alert_rule(
        rule_id=rule_id,
        product_code=product_code,
        metric=metric,
        threshold=threshold,
        window_days=window,
        delivery=delivery,
        delivery_config=delivery_cfg,
        description=description,
    )
    scope = product_code or "all products"
    console.print(f"[green]Alert rule {rule_id!r} created.[/green]")
    console.print(
        f"  metric={metric}, threshold={threshold}, window={window}d, "
        f"delivery={delivery}, scope={scope}"
    )


@alert_app.command("list")
def alert_list() -> None:
    """List all active alert rules.

    Example:
        maudesignal alert list
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    db = Database(config.db_path)
    rules = db.list_alert_rules(active_only=False)

    if not rules:
        console.print("[yellow]No alert rules defined. Use `alert add` to create one.[/yellow]")
        return

    table = Table(title="Alert Rules")
    table.add_column("ID", style="cyan")
    table.add_column("Metric")
    table.add_column("Threshold", justify="right")
    table.add_column("Window", justify="right")
    table.add_column("Delivery")
    table.add_column("Scope")
    table.add_column("Active")
    table.add_column("Description")

    for rule in rules:
        active_str = "[green]yes[/green]" if rule.active else "[red]no[/red]"
        table.add_row(
            rule.rule_id,
            rule.metric,
            str(rule.threshold),
            f"{rule.window_days}d",
            rule.delivery,
            rule.product_code or "all",
            active_str,
            rule.description or "",
        )
    console.print(table)


@alert_app.command("check")
def alert_check(
    product_code: str | None = typer.Option(
        None, "--product-code", "-p", help="Scope check to one product code."
    ),
) -> None:
    """Evaluate all active rules and fire notifications for any that trip.

    Example:
        maudesignal alert check
        maudesignal alert check --product-code QIH
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    db = Database(config.db_path)
    checker = AlertChecker(db)

    console.print("[green]Checking alert rules...[/green]")
    result = checker.check_all(product_code=product_code)

    console.print(
        f"Rules evaluated: {result.rules_evaluated} | "
        f"Fired: {result.alerts_fired} | "
        f"Delivered: {result.alerts_delivered}"
    )
    if result.details:
        table = Table(title="Fired Alerts")
        table.add_column("Rule ID")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Threshold", justify="right")
        table.add_column("Delivered")
        for d in result.details:
            delivered_str = "[green]yes[/green]" if d["delivered"] else "[red]no[/red]"
            table.add_row(
                d["rule_id"],
                d["metric"],
                f"{d['metric_value']:.3f}",
                f"{d['threshold']:.3f}",
                delivered_str,
            )
        console.print(table)
    else:
        console.print("[dim]No rules fired.[/dim]")


@alert_app.command("delete")
def alert_delete(
    rule_id: str = typer.Argument(..., help="Rule ID to deactivate."),
) -> None:
    """Deactivate an alert rule (soft-delete — history is preserved).

    Example:
        maudesignal alert delete abc12345
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    db = Database(config.db_path)
    found = db.deactivate_alert_rule(rule_id)
    if found:
        console.print(f"[green]Rule {rule_id!r} deactivated.[/green]")
    else:
        console.print(f"[red]Rule {rule_id!r} not found.[/red]")
        raise typer.Exit(code=1)


# ----------------------------------------------------------------------
# maudesignal forecast trends
# ----------------------------------------------------------------------


_NO_METRICS: list[str] = []


@forecast_app.command("trends")
def forecast_trends(
    product_code: str = typer.Argument(..., help="FDA product code to analyze."),
    metrics: list[str] = typer.Option(  # noqa: B008
        _NO_METRICS,
        "--metric",
        "-m",
        help="Metric to analyze. Repeat for multiple. Default: all.",
    ),
    window: int = typer.Option(90, "--window", "-w", help="Lookback window in days."),
    bucket: int = typer.Option(7, "--bucket", "-b", help="Bucket size in days."),
    min_periods: int = typer.Option(4, "--min-periods", help="Minimum non-empty buckets."),
) -> None:
    """Detect metric trends for a product code and store results.

    Example:
        maudesignal forecast trends QIH --metric ai_rate --window 90
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    chosen = list(metrics) if metrics else sorted(TREND_METRICS)
    for m in chosen:
        if m not in TREND_METRICS:
            console.print(f"[red]Unknown metric {m!r}. Choose from: {sorted(TREND_METRICS)}[/red]")
            raise typer.Exit(code=2)

    configure_logging(config.log_level)
    _print_startup(config)
    db = Database(config.db_path)
    extractor = Extractor(config=config, db=db)
    detector = TrendDetector(extractor=extractor, db=db, skills_root=config.project_root / "skills")

    console.print(
        f"[bold]Trend detection:[/bold] product={product_code} "
        f"metrics={chosen} window={window}d bucket={bucket}d"
    )

    results = detector.run(
        product_code=product_code,
        metrics=chosen,
        window_days=window,
        bucket_size_days=bucket,
        min_periods=min_periods,
    )

    table = Table(title=f"Trend Results — {product_code}", show_header=True)
    table.add_column("Metric")
    table.add_column("Direction")
    table.add_column("Strength")
    table.add_column("Signal")
    table.add_column("Sig?")
    table.add_column("Slope/period")
    table.add_column("Recent")
    table.add_column("Baseline")
    table.add_column("Status")

    for r in results:
        if r.skipped:
            table.add_row(
                r.metric_name,
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                f"[yellow]SKIPPED: {r.skip_reason}[/yellow]",
            )
            continue
        sig = "[green]Yes[/green]" if r.output.get("is_statistically_significant") else "No"
        direction = r.output.get("trend_direction", "?")
        strength = r.output.get("trend_strength", "?")
        signal = r.output.get("signal_level", "?")
        color = {"critical": "red", "elevated": "yellow", "routine": "cyan", "low": "dim"}.get(
            signal, "white"
        )
        table.add_row(
            r.metric_name,
            direction,
            strength,
            f"[{color}]{signal}[/{color}]",
            sig,
            f"{r.stats.slope_per_period:+.4f}",
            f"{r.stats.recent_value:.3f}",
            f"{r.stats.baseline_value:.3f}",
            f"[green]OK[/green] ({r.snapshot_id})",
        )

    console.print(table)

    for r in results:
        if not r.skipped and r.output.get("regulatory_narrative"):
            console.print(f"\n[bold]{r.metric_name} narrative:[/bold]")
            console.print(r.output["regulatory_narrative"])


# ----------------------------------------------------------------------
# maudesignal sources fetch
# ----------------------------------------------------------------------


@sources_app.command("fetch")
def sources_fetch(
    source: str = typer.Argument(..., help="Source to fetch: 'pubmed' or 'clinicaltrials'."),
    query: str = typer.Option(..., "--query", "-q", help="Search query string."),
    product_code: str | None = typer.Option(
        None, "--product-code", "-p", help="Tag fetched records with this product code."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum records to fetch."),
) -> None:
    """Fetch external publications or clinical trials and store them.

    Examples:
        maudesignal sources fetch pubmed --query "AI radiology adverse event" --product-code QIH
        maudesignal sources fetch clinicaltrials --query "artificial intelligence FDA cleared"
    """
    if source not in ("pubmed", "clinicaltrials"):
        console.print("[red]source must be 'pubmed' or 'clinicaltrials'[/red]")
        raise typer.Exit(code=2)

    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    db = Database(config.db_path)

    if source == "pubmed":
        import os

        api_key = os.environ.get("NCBI_API_KEY")
        fetcher = PubMedFetcher(db=db, api_key=api_key)
        console.print(f"[bold]Fetching PubMed:[/bold] query={query!r} limit={limit}")
        articles = fetcher.fetch(query=query, product_code=product_code, max_results=limit)
        fetcher.close()

        table = Table(title=f"PubMed Results ({len(articles)} articles)", show_header=True)
        table.add_column("PMID")
        table.add_column("Title", max_width=60)
        table.add_column("Authors", max_width=35)
        table.add_column("Date")
        for a in articles:
            table.add_row(a.pmid, a.title[:60], a.authors[:35], a.publication_date)
        console.print(table)

    else:
        fetcher_ct = ClinicalTrialsFetcher(db=db)
        console.print(f"[bold]Fetching ClinicalTrials.gov:[/bold] query={query!r} limit={limit}")
        trials = fetcher_ct.fetch(query=query, product_code=product_code, max_results=limit)
        fetcher_ct.close()

        table = Table(title=f"ClinicalTrials Results ({len(trials)} studies)", show_header=True)
        table.add_column("NCT ID")
        table.add_column("Title", max_width=50)
        table.add_column("Status")
        table.add_column("Phase")
        table.add_column("Start Date")
        for t in trials:
            table.add_row(t.nct_id, t.title[:50], t.status, t.phase, t.start_date)
        console.print(table)


@sources_app.command("list")
def sources_list(
    source_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by source type: pubmed or clinicaltrials."
    ),
    product_code: str | None = typer.Option(None, "--product-code", "-p"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """List stored external source records."""
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    db = Database(config.db_path)
    records = db.list_external_sources(
        source_type=source_type, product_code=product_code, limit=limit
    )

    if not records:
        console.print("[yellow]No external source records found.[/yellow]")
        return

    table = Table(title=f"External Sources ({len(records)} records)", show_header=True)
    table.add_column("Type")
    table.add_column("Source ID")
    table.add_column("Product")
    table.add_column("Title", max_width=55)
    table.add_column("Date")
    for r in records:
        table.add_row(
            r.source_type,
            r.source_id,
            r.product_code or "—",
            (r.title or "")[:55],
            r.publication_date or "—",
        )
    console.print(table)


# ----------------------------------------------------------------------
# maudesignal psur generate / list
# ----------------------------------------------------------------------


@psur_app.command("generate")
def psur_generate(
    product_code: str = typer.Argument(..., help="FDA product code to generate PSUR for."),
    device_name: str = typer.Option("", "--device-name", help="Human-readable device name."),
    window: int = typer.Option(180, "--window", "-w", help="Reporting window in days."),
) -> None:
    """Generate a PSUR draft for a product code using all pipeline outputs.

    Example:
        maudesignal psur generate QIH --device-name "AI Radiology System" --window 180
    """
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    configure_logging(config.log_level)
    _print_startup(config)
    db = Database(config.db_path)
    extractor = Extractor(config=config, db=db)
    generator = PsurGenerator(
        extractor=extractor,
        db=db,
        skills_root=config.project_root / "skills",
    )

    console.print(f"[bold]Generating PSUR draft:[/bold] product={product_code} window={window}d")
    draft = generator.generate(
        product_code=product_code,
        device_name=device_name,
        window_days=window,
    )

    signal_color = {
        "confirmed_signal": "red",
        "potential_signal": "yellow",
        "no_signal": "green",
    }.get(draft.signal_assessment, "white")

    console.print(
        f"\n[bold]Report ID:[/bold] {draft.report_id}\n"
        f"[bold]Period:[/bold] {draft.reporting_period_start} to {draft.reporting_period_end}\n"
        f"[bold]Signal:[/bold] [{signal_color}]{draft.signal_assessment}[/{signal_color}]\n"
        f"[bold]Confidence:[/bold] {draft.confidence_score:.2f}\n"
    )
    console.print("[bold]Executive Summary:[/bold]")
    console.print(draft.executive_summary)

    if draft.sections:
        console.print("\n[bold]Sections:[/bold]")
        for sec in draft.sections:
            console.print(f"\n[dim]{sec.get('title', '')}[/dim]")
            console.print(sec.get("content", ""))

    if draft.recommended_actions:
        console.print("\n[bold]Recommended Actions:[/bold]")
        for i, action in enumerate(draft.recommended_actions, 1):
            console.print(f"  {i}. {action}")


@psur_app.command("list")
def psur_list(
    product_code: str | None = typer.Option(None, "--product-code", "-p"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """List stored PSUR report drafts."""
    try:
        config = Config.load()
    except ConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    db = Database(config.db_path)
    reports = db.list_psur_reports(product_code=product_code, limit=limit)

    if not reports:
        console.print("[yellow]No PSUR reports found.[/yellow]")
        return

    table = Table(title=f"PSUR Reports ({len(reports)} found)", show_header=True)
    table.add_column("Report ID")
    table.add_column("Product")
    table.add_column("Period")
    table.add_column("Signal")
    table.add_column("Confidence")
    table.add_column("Drafted At")
    for r in reports:
        signal_color = {
            "confirmed_signal": "red",
            "potential_signal": "yellow",
            "no_signal": "green",
        }.get(r.signal_assessment, "white")
        table.add_row(
            r.report_id,
            r.product_code,
            f"{r.reporting_period_start} → {r.reporting_period_end}",
            f"[{signal_color}]{r.signal_assessment}[/{signal_color}]",
            f"{r.confidence_score:.2f}",
            str(r.drafted_at)[:16],
        )
    console.print(table)


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
