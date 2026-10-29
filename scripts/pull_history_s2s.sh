#!/usr/bin/env bash
# The one-off S2S history pull. Run it on a machine that can stay up for days; it is resumable
# (request ids in state/requests.json, decoded dates skipped) so Ctrl-C and rerun is fine.
# GRIB is kept under state/grib/ (gitignored) after decode, in case indices need reprocessing
# from the raw fields; the decoded state (state/members/) is megabytes per month regardless.
#
#   ECMWF_API_KEY=... scripts/pull_history_s2s.sh [origins] [start] [end] [priority_reforecast_end] [parallel]
#   defaults: ecmwf 2016-10-01 2023-04-30 (Duet validation winter + the seven open test winters)
#   priority_reforecast_end (optional): pull reforecast jobs up to this month first, e.g. to get a
#   couple of winters' reforecasts in front of a build session without waiting for all 49 months.
#   parallel (optional): requests in flight at once on ECDS (default 1, same as pull_s2s.py, since
#   ECMWF's 2026-10 Data Stores service-protection measures explicitly ask for sequential
#   submission, not parallel, on pain of account suspension -- see
#   https://forum.ecmwf.int/t/data-stores-service-protection-measures-affecting-data-downloads-and-account-access-cds-ads-ewds-ecds/15481
#   and docs/agents/lessons-s2s-history-pull.md. The original 2016-10 history pull ran at 2 and
#   found that a sweet spot against high rejection rates at 4, but that predates this policy.
#   then:     .venv/bin/python scripts/state_release.py upload   # publish the decoded state for CI
# Optional: with GITHUB_TOKEN and GITHUB_REPOSITORY set, the decoded state is uploaded as a release
# after every loop, so progress is visible from anywhere (and nothing is lost if the box dies).
# Status at any time: scripts/pull_status.py (also logs/status.json).
set -euo pipefail; cd "$(dirname "$0")/.."
: "${ECMWF_API_KEY:?set ECMWF_API_KEY (the one key for ECDS and CDS; licences accepted on both)}"
ORIGINS="${1:-ecmwf}"; START="${2:-2016-10-01}"; END="${3:-2023-04-30}"; PRIORITY_RF_END="${4:-}"; PARALLEL="${5:-}"
PRIO_ARGS=(); [ -n "$PRIORITY_RF_END" ] && PRIO_ARGS=(--priority-reforecast-end "$PRIORITY_RF_END")
PARALLEL_ARGS=(); [ -n "$PARALLEL" ] && PARALLEL_ARGS=(--parallel "$PARALLEL")
mkdir -p logs
while true; do
  .venv/bin/python scripts/pull_s2s.py --origins "$ORIGINS" --start "$START" --end "$END" --budget-s 86400 "${PRIO_ARGS[@]}" "${PARALLEL_ARGS[@]}" 2>&1 | tee -a logs/pull_history_s2s.log
  .venv/bin/python scripts/pull_status.py || true
  if [ -n "${GITHUB_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ]; then
    .venv/bin/python scripts/state_release.py upload --keep 3 || echo "checkpoint upload failed; continuing"
  fi
  if .venv/bin/python scripts/pull_s2s.py --origins "$ORIGINS" --start "$START" --end "$END" --dry-run 2>&1 | grep -q " 0 requests to fetch"; then
    echo "history pull complete"; break
  fi
  echo "resuming in 60 s"; sleep 60
done
