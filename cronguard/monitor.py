"""Core monitoring logic — checks each job and returns findings."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .schedule import CronSchedule
from .store import CronStore, JobDef, Heartbeat


@dataclass
class JobStatus:
    job: JobDef
    last_seen: Optional[datetime]    # UTC, None if never seen
    expected_at: Optional[datetime]  # last scheduled time
    missed: bool
    late_by_seconds: float           # 0 if not missed

    @property
    def late_by_human(self) -> str:
        s = self.late_by_seconds
        if s <= 0:
            return "on time"
        if s < 60:
            return f"{s:.0f}s late"
        if s < 3600:
            return f"{s / 60:.1f}m late"
        return f"{s / 3600:.1f}h late"


@dataclass
class MonitorReport:
    statuses: List[JobStatus] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def missed_jobs(self) -> List[JobStatus]:
        return [s for s in self.statuses if s.missed]

    @property
    def healthy_jobs(self) -> List[JobStatus]:
        return [s for s in self.statuses if not s.missed]

    @property
    def has_missed(self) -> bool:
        return bool(self.missed_jobs)


def check_all(store: CronStore, now: Optional[datetime] = None) -> MonitorReport:
    """Check every enabled job and return a MonitorReport."""
    if now is None:
        now = datetime.now(timezone.utc)

    jobs = [j for j in store.list_jobs() if j.enabled]
    statuses: List[JobStatus] = []

    for job in jobs:
        hb = store.get_heartbeat(job.name)
        last_seen = hb.last_seen if hb else None

        try:
            sched = CronSchedule(job.schedule)
            expected_at = sched.expected_before(now, grace_seconds=job.grace_seconds)
        except Exception:
            expected_at = None

        if expected_at is None:
            # Job hasn't been scheduled yet
            statuses.append(JobStatus(
                job=job, last_seen=last_seen, expected_at=None,
                missed=False, late_by_seconds=0,
            ))
            continue

        if last_seen is None:
            missed = True
            late_by = (now - expected_at).total_seconds()
        else:
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if expected_at.tzinfo is None:
                expected_at = expected_at.replace(tzinfo=timezone.utc)
            missed = last_seen < expected_at
            late_by = max(0.0, (now - last_seen).total_seconds() - job.grace_seconds) if missed else 0.0

        statuses.append(JobStatus(
            job=job,
            last_seen=last_seen,
            expected_at=expected_at,
            missed=missed,
            late_by_seconds=late_by,
        ))

    return MonitorReport(statuses=statuses, checked_at=now)
