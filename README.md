# cronguard

**Monitor cron jobs for missed runs — get alerted before your users notice.**

Most monitoring tools check if a *service* is up. `cronguard` checks if your *scheduled jobs actually ran* — backups, report generators, cleanup tasks, email senders. Know within minutes when one silently fails.

```bash
pip install cronguard
```

[![CI](https://github.com/bhupendra05/cronguard/actions/workflows/ci.yml/badge.svg)](https://github.com/bhupendra05/cronguard/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Quick start

```bash
# 1. Register a job (runs hourly, 60s grace period)
cronguard register nightly-backup "0 2 * * *" --grace 300

# 2. In your cron job script, report success:
cronguard heartbeat nightly-backup

# 3. Check status (run from another cron job or monitoring script)
cronguard check

# 4. Fail in CI if any jobs are missed
cronguard check --fail-on-missed
```

---

## CLI reference

```bash
# Register a job
cronguard register <name> "<cron expression>" [--grace SECONDS]

# Record a successful run
cronguard heartbeat <name>

# List all registered jobs
cronguard jobs

# Check all jobs for missed runs
cronguard check
cronguard check --json
cronguard check --fail-on-missed   # exit 1 if any missed

# Remove a job
cronguard unregister <name>

# Use a custom state file (default: ~/.cronguard/jobs.db)
cronguard --db /var/lib/cronguard/jobs.db check
```

**Example check output:**

```
cronguard check — 2024-06-15 14:30 UTC
Healthy: 2  Missed: 1

  ✔ nightly-backup              last=2024-06-15 02:01
  ✔ weekly-report               last=2024-06-10 00:00
  ✘ db-vacuum                   last=never  [2h late]
```

---

## Python API

```python
from cronguard import CronStore, JobDef, check_all

store = CronStore.open("~/.cronguard/jobs.db")

# Register
store.register(JobDef("db-backup", "0 2 * * *", grace_seconds=300))

# Record heartbeat from your backup script
store.heartbeat("db-backup")

# Check for missed jobs
report = check_all(store)
for status in report.missed_jobs:
    print(f"MISSED: {status.job.name} — {status.late_by_human}")
```

---

## Supported cron syntax

```
# ┌───── minute (0–59)
# │ ┌──── hour (0–23)
# │ │ ┌─── day of month (1–31)
# │ │ │ ┌── month (1–12 or jan–dec)
# │ │ │ │ ┌─ day of week (0–6, 0=Sun or sun–sat)
# │ │ │ │ │
# * * * * *

*/5 * * * *     # every 5 minutes
0 9-17 * * 1-5  # every hour 9am–5pm, weekdays
0 2 * * *       # daily at 2am
@hourly         # alias for 0 * * * *
@daily          # alias for 0 0 * * *
@weekly         # alias for 0 0 * * 0
@monthly        # alias for 0 0 1 * *
```

---

## CI/CD integration

Add to your Makefile or CI pipeline:

```bash
# After running your jobs, check for any that missed
cronguard check --fail-on-missed --json | tee cronguard-report.json
```

---

## License

MIT © [Bhupendra Tale](https://github.com/bhupendra05)
