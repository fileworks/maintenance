"""Dependency-automation metrics shared by the Renovate policy tooling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AutomationMetrics:
    """One month of dependency-update activity, for evidence-based tuning."""

    opened: int = 0
    grouped: int = 0
    automerged: int = 0
    manual: int = 0
    failed: int = 0
    stale: int = 0

    @property
    def automerge_rate(self) -> float:
        return 0.0 if self.opened == 0 else self.automerged / self.opened

    @property
    def needs_attention(self) -> int:
        return self.manual + self.failed + self.stale

    def summary(self) -> str:
        return (
            f"{self.opened} opened · {self.automerged} automerged "
            f"({self.automerge_rate:.0%}) · {self.needs_attention} needing attention"
        )

    def recommendation(self) -> str:
        if self.opened == 0:
            return "No updates were opened; nothing to tune yet."
        if self.failed > self.automerged:
            return "More updates failed than merged: inspect failures before raising limits."
        if self.stale > 0:
            return f"{self.stale} update(s) went stale: raise the PR limit or group harder."
        if self.automerge_rate > 0.8 and self.needs_attention <= 2:
            return "Automation is carrying the load; the current limits are right."
        return "Keep the current limits for another cycle before changing anything."


@dataclass(frozen=True)
class MetricsBaseline:
    """The first month's numbers, recorded so later months mean something."""

    recorded_on: str | None = None
    metrics: AutomationMetrics | None = None

    @property
    def established(self) -> bool:
        return self.metrics is not None and self.recorded_on is not None

    def compare(self, current: AutomationMetrics) -> str:
        if not self.established or self.metrics is None:
            return (
                "No baseline has been recorded yet. This month's numbers become the "
                "baseline; nothing should be tuned from a single month."
            )
        delta_opened = current.opened - self.metrics.opened
        delta_rate = current.automerge_rate - self.metrics.automerge_rate
        direction = "up" if delta_opened > 0 else "down" if delta_opened < 0 else "flat"
        return (
            f"Opened {direction} by {abs(delta_opened)} against the {self.recorded_on} baseline; "
            f"automerge rate {current.automerge_rate:.0%} "
            f"({'+' if delta_rate >= 0 else ''}{delta_rate:.0%})."
        )


def metrics_markdown(monthly: dict[str, AutomationMetrics], baseline: MetricsBaseline) -> str:
    """Render monthly dependency automation metrics and a recommendation."""
    lines = [
        "| Month | Opened | Grouped | Automerged | Manual | Failed | Stale | Rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for month in sorted(monthly):
        item = monthly[month]
        lines.append(
            f"| {month} | {item.opened} | {item.grouped} | {item.automerged} | "
            f"{item.manual} | {item.failed} | {item.stale} | {item.automerge_rate:.0%} |"
        )
    latest = monthly[max(monthly)] if monthly else AutomationMetrics()
    lines += ["", baseline.compare(latest), "", f"**Recommendation.** {latest.recommendation()}"]
    return "\n".join(lines)
