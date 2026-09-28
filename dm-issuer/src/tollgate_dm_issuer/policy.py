"""Policy engine — whitelist + per-npub caps + hourly throttle + global cap.

A single ``PolicyEngine.check`` call answers the ADMIT or REJECT decision for
an incoming DM request envelope. The journal interface (`journal.Journal`)
provides the accounting primitives (`commit_usage`, `get_usage`,
`get_pending_usage`, `count_recent_requests`, `reserve_request`).

State machine usage (DM-ST-2/3):

* ``check`` reserves a request slot + (pending amount) on ALLOW so the next
  in-flight request sees the right projection; ``commit_usage`` is then called
  by the dispatcher only on DELIVERED — turning that pending amount into
  committed sat usage.

Spec references: §2 DM-ST-1..5, §3.3 error codes, §4 DM-CFG-1..6.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import Config
from .journal import Journal, day_utc

log = logging.getLogger(__name__)


class DecisionKind(str, enum.Enum):
    ALLOW = "ALLOW"
    NOT_WHITELISTED = "NOT_WHITELISTED"
    SILENT_DROP = "SILENT_DROP"
    REJECTED = "REJECTED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    code: Optional[str] = None
    message: Optional[str] = None
    retry_after_secs: Optional[int] = None
    request_id: Optional[str] = None


NOT_WHITELISTED_REPLY_LIMIT = 1


class PolicyEngine:
    def __init__(self, *, config: Config, journal: Journal) -> None:
        self.config = config
        self.journal = journal

    def check(
        self,
        npub: str,
        amount: int,
        *,
        now: datetime,
        created_at: datetime,
        event_id: str,
    ) -> Decision:
        entry = self.config.whitelist_entry(npub)
        if entry is None:
            return self._not_whitelisted(npub, now)

        if amount < self.config.min_request_sats:
            return Decision(
                kind=DecisionKind.REJECTED,
                code="AMOUNT_INVALID",
                message=f"amount {amount} is below the minimum of {self.config.min_request_sats} sats",
            )
        effective_max = self.config.effective_max_request_sats(
            npub, self.config.registry_max_single_issuance
        )
        if amount > effective_max:
            return Decision(
                kind=DecisionKind.REJECTED,
                code="AMOUNT_INVALID",
                message=f"amount {amount} exceeds effective max of {effective_max} sats for {npub}",
            )

        age = (now - created_at).total_seconds()
        if age > self.config.stale_request_secs:
            return Decision(
                kind=DecisionKind.REJECTED,
                code="STALE_REQUEST",
                message=f"request created {int(age)}s ago is older than the {self.config.stale_request_secs}s stale threshold",
            )

        day = day_utc(now)
        issued, committed_sats = self.journal.get_usage(npub, day)
        pending_sats = self.journal.get_pending_usage(npub, day)
        projected_sats = committed_sats + pending_sats + amount

        window_start = now - timedelta(hours=1)
        requests_in_hour = self.journal.count_recent_requests(npub, window_start)
        if requests_in_hour >= self.config.max_requests_per_hour:
            retry_after = max(1, int((now + timedelta(hours=1) - now).total_seconds()))
            return Decision(
                kind=DecisionKind.REJECTED,
                code="RATE_LIMITED",
                message=f"exceeded {self.config.max_requests_per_hour} requests/hour ({requests_in_hour} already sent)",
                retry_after_secs=retry_after,
            )

        global_issued = self.journal.get_global_usage(day)
        global_pending = sum(
            self.journal.get_pending_usage(e.npub, day) for e in self.config.whitelist
        )
        projected_global = global_issued + global_pending + amount
        if (entry.daily_cap_sats > 0 and projected_sats > entry.daily_cap_sats):
            retry_after = self._retry_until_next_day(now)
            remaining = max(0, entry.daily_cap_sats - committed_sats - pending_sats)
            return Decision(
                kind=DecisionKind.REJECTED,
                code="DAILY_CAP_EXCEEDED",
                message=(
                    f"daily cap {entry.daily_cap_sats} sats would be exceeded "
                    f"(committed {committed_sats} + pending {pending_sats} + "
                    f"requested {amount} = {projected_sats}); remaining {remaining}"
                ),
                retry_after_secs=retry_after,
            )
        if projected_global > self.config.global_daily_cap_sats:
            retry_after = self._retry_until_next_day(now)
            return Decision(
                kind=DecisionKind.REJECTED,
                code="GLOBAL_CAP_EXCEEDED",
                message=(
                    f"global daily cap {self.config.global_daily_cap_sats} sats would be exceeded "
                    f"(issued {global_issued} + pending {global_pending} + requested {amount})"
                ),
                retry_after_secs=retry_after,
            )

        self.journal.reserve_request(npub, event_id, amount, now)
        log.info("ALLOW npub=%s amount=%d event_id=%s", npub, amount, event_id)
        return Decision(kind=DecisionKind.ALLOW, request_id=None)

    def commit_usage(self, npub: str, amount: int, ts: datetime) -> None:
        self.journal.commit_usage(npub, amount, ts)

    def _not_whitelisted(self, npub: str, now: datetime) -> Decision:
        day = day_utc(now)
        if self.journal.count_recent_requests(npub, datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)) >= 1:
            log.warning("SILENT_DROP npub=%s (already warned today)", npub)
            return Decision(kind=DecisionKind.SILENT_DROP, code="NOT_WHITELISTED")
        self.journal.reserve_request(npub, f"not_whitelisted:{npub}:{day}", 0, now)
        return Decision(
            kind=DecisionKind.NOT_WHITELISTED,
            code="NOT_WHITELISTED",
            message="this npub is not on the issuer whitelist; contact the operator",
        )

    @staticmethod
    def _retry_until_next_day(now: datetime) -> int:
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(1, int((tomorrow - now).total_seconds()))
