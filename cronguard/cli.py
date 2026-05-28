"""CLI for cronguard."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from .store import CronStore, JobDef
from .monitor import check_all

_DEFAULT_DB = os.path.expanduser("~/.cronguard/jobs.db")


def _get_store(db: str) -> CronStore:
    return CronStore.open(db)


@click.group()
@click.option("--db", default=_DEFAULT_DB, show_default=True, envvar="CRONGUARD_DB",
              help="Path to the SQLite state file.")
@click.pass_context
def cli(ctx: click.Context, db: str) -> None:
    """cronguard — monitor cron jobs for missed runs."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db


@cli.command("register")
@click.argument("name")
@click.argument("schedule")
@click.option("--grace", default=60, show_default=True, help="Grace period in seconds.")
@click.pass_context
def register(ctx, name: str, schedule: str, grace: int) -> None:
    """Register a cron job NAME with SCHEDULE (e.g. '0 * * * *')."""
    store = _get_store(ctx.obj["db"])
    store.register(JobDef(name=name, schedule=schedule, grace_seconds=grace))
    click.echo(f"Registered: {name!r}  schedule={schedule!r}  grace={grace}s")


@cli.command("unregister")
@click.argument("name")
@click.pass_context
def unregister(ctx, name: str) -> None:
    """Remove a registered job."""
    store = _get_store(ctx.obj["db"])
    ok = store.unregister(name)
    if ok:
        click.echo(f"Removed: {name!r}")
    else:
        click.echo(f"Job not found: {name!r}", err=True)
        sys.exit(1)


@cli.command("heartbeat")
@click.argument("name")
@click.pass_context
def heartbeat(ctx, name: str) -> None:
    """Record that job NAME ran successfully right now."""
    store = _get_store(ctx.obj["db"])
    store.heartbeat(name)
    click.echo(f"Heartbeat recorded for: {name!r}")


@cli.command("jobs")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def list_jobs(ctx, as_json: bool) -> None:
    """List all registered jobs."""
    store = _get_store(ctx.obj["db"])
    jobs = store.list_jobs()
    if as_json:
        click.echo(json.dumps([
            {"name": j.name, "schedule": j.schedule,
             "grace_seconds": j.grace_seconds, "enabled": j.enabled}
            for j in jobs
        ], indent=2))
    else:
        if not jobs:
            click.echo("No jobs registered.")
            return
        click.echo(f"\n{'NAME':<30} {'SCHEDULE':<20} {'GRACE':>8}  ENABLED")
        click.echo("-" * 65)
        for j in jobs:
            click.echo(f"{j.name:<30} {j.schedule:<20} {j.grace_seconds:>7}s  {'yes' if j.enabled else 'no'}")
        click.echo()


@cli.command("check")
@click.option("--json", "as_json", is_flag=True)
@click.option("--fail-on-missed", is_flag=True, help="Exit 1 if any jobs are missed.")
@click.pass_context
def check(ctx, as_json: bool, fail_on_missed: bool) -> None:
    """Check all jobs for missed runs."""
    store = _get_store(ctx.obj["db"])
    report = check_all(store)

    if as_json:
        click.echo(json.dumps({
            "checked_at": report.checked_at.isoformat(),
            "missed": len(report.missed_jobs),
            "healthy": len(report.healthy_jobs),
            "statuses": [
                {
                    "name": s.job.name,
                    "schedule": s.job.schedule,
                    "missed": s.missed,
                    "last_seen": s.last_seen.isoformat() if s.last_seen else None,
                    "expected_at": s.expected_at.isoformat() if s.expected_at else None,
                    "late_by_seconds": s.late_by_seconds,
                }
                for s in report.statuses
            ],
        }, indent=2))
    else:
        click.echo(f"\ncronguard check — {report.checked_at.strftime('%Y-%m-%d %H:%M UTC')}")
        click.echo(f"Healthy: {len(report.healthy_jobs)}  Missed: {len(report.missed_jobs)}\n")
        for s in report.statuses:
            icon = click.style("✔", fg="green") if not s.missed else click.style("✘", fg="red")
            last = s.last_seen.strftime("%Y-%m-%d %H:%M") if s.last_seen else "never"
            status = "" if not s.missed else f"  [{s.late_by_human}]"
            click.echo(f"  {icon} {s.job.name:<28} last={last}{status}")
        click.echo()

    if fail_on_missed and report.has_missed:
        sys.exit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
