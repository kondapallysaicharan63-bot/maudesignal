"""Alert rule definitions and constants (Phase 2)."""

from __future__ import annotations

from typing import Literal

AlertMetric = Literal["new_reports", "ai_rate", "severity_rate", "new_failure_mode"]
DeliveryChannel = Literal["console", "slack", "email"]

VALID_METRICS: set[str] = {"new_reports", "ai_rate", "severity_rate", "new_failure_mode"}
VALID_DELIVERY: set[str] = {"console", "slack", "email"}


def validate_metric(metric: str) -> None:
    """Raise ValueError if metric is not recognised."""
    if metric not in VALID_METRICS:
        raise ValueError(f"Unknown metric {metric!r}. Valid: {sorted(VALID_METRICS)}")


def validate_delivery(delivery: str) -> None:
    """Raise ValueError if delivery channel is not recognised."""
    if delivery not in VALID_DELIVERY:
        raise ValueError(f"Unknown delivery {delivery!r}. Valid: {sorted(VALID_DELIVERY)}")


class AlertRule:
    """Value object wrapping an AlertRuleRecord for business logic."""

    __slots__ = (
        "rule_id",
        "product_code",
        "metric",
        "threshold",
        "window_days",
        "delivery",
        "delivery_config",
        "description",
    )

    def __init__(
        self,
        *,
        rule_id: str,
        product_code: str | None,
        metric: str,
        threshold: float,
        window_days: int,
        delivery: str,
        delivery_config: dict[str, str] | None = None,
        description: str | None = None,
    ) -> None:
        """Initialize and validate an alert rule."""
        validate_metric(metric)
        validate_delivery(delivery)
        self.rule_id = rule_id
        self.product_code = product_code
        self.metric = metric
        self.threshold = threshold
        self.window_days = window_days
        self.delivery = delivery
        self.delivery_config: dict[str, str] = delivery_config or {}
        self.description = description

    def __repr__(self) -> str:
        """Return developer-readable representation."""
        return (
            f"AlertRule(id={self.rule_id!r}, metric={self.metric!r}, "
            f"threshold={self.threshold}, window={self.window_days}d, "
            f"delivery={self.delivery!r})"
        )
