"""Tests for cronguard — cron schedule parser + missed-run monitor."""
import pytest
from datetime import datetime, timezone, timedelta
from cronguard.schedule import CronSchedule, _expand_field
from cronguard.store import CronStore, JobDef, Heartbeat
from cronguard.monitor import check_all, JobStatus


# ---------------------------------------------------------------------------
# _expand_field
# ---------------------------------------------------------------------------

class TestExpandField:
    def test_wildcard_minute(self):
        assert _expand_field("*", 0, 59) == list(range(60))

    def test_single_value(self):
        assert _expand_field("5", 0, 59) == [5]

    def test_range(self):
        assert _expand_field("1-5", 0, 59) == [1, 2, 3, 4, 5]

    def test_step_from_wildcard(self):
        assert _expand_field("*/15", 0, 59) == [0, 15, 30, 45]

    def test_step_from_range(self):
        assert _expand_field("0-30/10", 0, 59) == [0, 10, 20, 30]

    def test_comma_list(self):
        assert _expand_field("1,3,5", 0, 59) == [1, 3, 5]

    def test_month_names(self):
        assert _expand_field("jan", 1, 12) == [1]
        assert _expand_field("dec", 1, 12) == [12]

    def test_dow_names(self):
        assert _expand_field("sun", 0, 6) == [0]
        assert _expand_field("sat", 0, 6) == [6]


# ---------------------------------------------------------------------------
# CronSchedule
# ---------------------------------------------------------------------------

def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class TestCronSchedule:
    def test_invalid_expression_raises(self):
        with pytest.raises(ValueError):
            CronSchedule("* * * *")  # only 4 fields

    def test_every_minute(self):
        s = CronSchedule("* * * * *")
        base = _utc(2024, 1, 1, 12, 0)
        nxt = s.next_after(base)
        assert nxt == _utc(2024, 1, 1, 12, 1)

    def test_every_hour(self):
        s = CronSchedule("0 * * * *")
        base = _utc(2024, 1, 1, 12, 30)
        nxt = s.next_after(base)
        assert nxt == _utc(2024, 1, 1, 13, 0)

    def test_daily_midnight(self):
        s = CronSchedule("0 0 * * *")
        base = _utc(2024, 3, 15, 10, 0)
        nxt = s.next_after(base)
        assert nxt == _utc(2024, 3, 16, 0, 0)

    def test_monthly(self):
        s = CronSchedule("0 9 1 * *")
        base = _utc(2024, 3, 2, 9, 0)
        nxt = s.next_after(base)
        assert nxt == _utc(2024, 4, 1, 9, 0)

    def test_named_daily(self):
        s = CronSchedule("@daily")
        base = _utc(2024, 6, 15, 12, 0)
        nxt = s.next_after(base)
        assert nxt == _utc(2024, 6, 16, 0, 0)

    def test_named_hourly(self):
        s = CronSchedule("@hourly")
        base = _utc(2024, 6, 15, 12, 30)
        nxt = s.next_after(base)
        assert nxt == _utc(2024, 6, 15, 13, 0)

    def test_named_weekly(self):
        s = CronSchedule("@weekly")
        # @weekly = 0 0 * * 0 (Sunday midnight)
        base = _utc(2024, 6, 10, 0, 0)  # Monday
        nxt = s.next_after(base)
        assert nxt.weekday() == 6  # Sunday in Python

    def test_next_after_exact_match_is_excluded(self):
        s = CronSchedule("30 9 * * *")
        exact = _utc(2024, 1, 1, 9, 30)
        nxt = s.next_after(exact)
        assert nxt == _utc(2024, 1, 2, 9, 30)

    def test_step_schedule(self):
        s = CronSchedule("*/10 * * * *")
        base = _utc(2024, 1, 1, 12, 5)
        nxt = s.next_after(base)
        assert nxt == _utc(2024, 1, 1, 12, 10)

    def test_expected_before_returns_past_time(self):
        s = CronSchedule("0 * * * *")  # every hour
        now = _utc(2024, 6, 15, 14, 45)
        expected = s.expected_before(now, grace_seconds=0)
        assert expected is not None
        assert expected <= now
        assert expected == _utc(2024, 6, 15, 14, 0)

    def test_expected_before_with_grace(self):
        s = CronSchedule("0 * * * *")
        # 1 minute after the hour — grace=120s means expected_before uses now-2min
        now = _utc(2024, 6, 15, 14, 1)
        expected = s.expected_before(now, grace_seconds=120)
        # now - 120s = 13:59 → last scheduled before that = 13:00
        assert expected == _utc(2024, 6, 15, 13, 0)


# ---------------------------------------------------------------------------
# CronStore
# ---------------------------------------------------------------------------

class TestCronStore:
    def _store(self):
        return CronStore(":memory:")

    def test_register_and_get(self):
        s = self._store()
        s.register(JobDef("backup", "0 2 * * *", grace_seconds=300))
        j = s.get_job("backup")
        assert j is not None
        assert j.name == "backup"
        assert j.schedule == "0 2 * * *"
        assert j.grace_seconds == 300

    def test_register_upsert(self):
        s = self._store()
        s.register(JobDef("backup", "0 2 * * *", grace_seconds=60))
        s.register(JobDef("backup", "0 3 * * *", grace_seconds=120))
        j = s.get_job("backup")
        assert j.schedule == "0 3 * * *"
        assert j.grace_seconds == 120

    def test_unregister(self):
        s = self._store()
        s.register(JobDef("cleanup", "0 4 * * *", grace_seconds=60))
        assert s.unregister("cleanup") is True
        assert s.get_job("cleanup") is None

    def test_unregister_nonexistent_returns_false(self):
        s = self._store()
        assert s.unregister("nope") is False

    def test_list_jobs_empty(self):
        assert self._store().list_jobs() == []

    def test_list_jobs_sorted(self):
        s = self._store()
        s.register(JobDef("z_job", "* * * * *", 60))
        s.register(JobDef("a_job", "* * * * *", 60))
        names = [j.name for j in s.list_jobs()]
        assert names == sorted(names)

    def test_heartbeat_recorded(self):
        s = self._store()
        t = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        s.heartbeat("myjob", at=t)
        hb = s.get_heartbeat("myjob")
        assert hb is not None
        assert hb.last_seen == t

    def test_heartbeat_overwrite(self):
        s = self._store()
        t1 = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2024, 6, 1, 13, 0, tzinfo=timezone.utc)
        s.heartbeat("myjob", at=t1)
        s.heartbeat("myjob", at=t2)
        assert s.get_heartbeat("myjob").last_seen == t2

    def test_get_heartbeat_none_if_never_seen(self):
        s = self._store()
        assert s.get_heartbeat("unknown") is None

    def test_heartbeat_without_at_uses_now(self):
        s = self._store()
        s.heartbeat("myjob")
        hb = s.get_heartbeat("myjob")
        diff = abs((datetime.now(timezone.utc) - hb.last_seen).total_seconds())
        assert diff < 5


# ---------------------------------------------------------------------------
# check_all
# ---------------------------------------------------------------------------

class TestMonitor:
    def _setup(self, schedule="0 * * * *", grace=60):
        """Store with one job registered, returns (store, now)."""
        store = CronStore(":memory:")
        store.register(JobDef("testjob", schedule, grace_seconds=grace))
        return store

    def test_no_heartbeat_means_missed(self):
        store = self._setup()
        now = _utc(2024, 6, 15, 14, 30)
        report = check_all(store, now=now)
        assert report.has_missed
        assert report.missed_jobs[0].job.name == "testjob"

    def test_recent_heartbeat_is_healthy(self):
        store = self._setup()
        now = _utc(2024, 6, 15, 14, 30)
        # heartbeat at the last scheduled time (14:00)
        store.heartbeat("testjob", at=_utc(2024, 6, 15, 14, 0))
        report = check_all(store, now=now)
        assert not report.has_missed

    def test_stale_heartbeat_is_missed(self):
        store = self._setup()
        now = _utc(2024, 6, 15, 14, 30)
        # last heartbeat was 13:00, but expected at 14:00
        store.heartbeat("testjob", at=_utc(2024, 6, 15, 13, 0))
        report = check_all(store, now=now)
        assert report.has_missed

    def test_disabled_job_skipped(self):
        store = CronStore(":memory:")
        store.register(JobDef("disabled_job", "0 * * * *", grace_seconds=60, enabled=False))
        report = check_all(store, now=_utc(2024, 6, 15, 14, 30))
        assert len(report.statuses) == 0

    def test_multiple_jobs_mixed_health(self):
        store = CronStore(":memory:")
        store.register(JobDef("healthy", "0 * * * *", 60))
        store.register(JobDef("missed",  "0 * * * *", 60))
        now = _utc(2024, 6, 15, 14, 30)
        store.heartbeat("healthy", at=_utc(2024, 6, 15, 14, 0))
        report = check_all(store, now=now)
        assert len(report.healthy_jobs) == 1
        assert len(report.missed_jobs) == 1
        assert report.healthy_jobs[0].job.name == "healthy"
        assert report.missed_jobs[0].job.name == "missed"

    def test_late_by_human_on_time(self):
        status = JobStatus(
            job=JobDef("j", "* * * * *", 60),
            last_seen=None, expected_at=None,
            missed=False, late_by_seconds=0,
        )
        assert status.late_by_human == "on time"

    def test_late_by_human_seconds(self):
        status = JobStatus(
            job=JobDef("j", "* * * * *", 60),
            last_seen=None, expected_at=None,
            missed=True, late_by_seconds=45,
        )
        assert "45s" in status.late_by_human

    def test_late_by_human_minutes(self):
        status = JobStatus(
            job=JobDef("j", "* * * * *", 60),
            last_seen=None, expected_at=None,
            missed=True, late_by_seconds=90,
        )
        assert "m" in status.late_by_human

    def test_late_by_human_hours(self):
        status = JobStatus(
            job=JobDef("j", "* * * * *", 60),
            last_seen=None, expected_at=None,
            missed=True, late_by_seconds=7200,
        )
        assert "h" in status.late_by_human

    def test_report_checked_at_is_utc(self):
        store = CronStore(":memory:")
        now = _utc(2024, 6, 15, 10, 0)
        report = check_all(store, now=now)
        assert report.checked_at == now
