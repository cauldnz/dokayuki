# Lessons from the ECMWF S2S history pull (16–24 Oct 2026)

What actually slowed the pull down, what didn't, and what to do differently next time a
long-running ECDS job runs on this laptop (or wherever `ecmwf-haul` ends up living). Written
after the pull finished (`state-20261023T193533Z`, 104 months decoded, ~8 days wall-clock).

## The ECDS rejection problem

Submissions get silently `rejected` (empty `log: []`, no explanation) at a rate that depends on
`--parallel`, not on request content — the same request resubmitted later usually succeeds.

| `--parallel` | Behaviour observed |
|---|---|
| 4 (the default) | Fine for the first ~24 h, then rejection rate climbed to 50–70% and stayed there. A 6 h pause (stop, wait, restart) did **not** clear it — disproves "it just needs to cool down". |
| 1 | Rejections dropped to ~0%, but so did throughput: ECDS's single server-side worker slot means one in-flight request serializes everything, and a slow request stalls the whole pull for the retry-sleep interval. Net progress over ~1 h: effectively zero. |
| 2 | The sweet spot found by trial. Rejection rate settled around 5–15% over many consecutive hours, isolated to single fields rather than whole months, and the resumable design just retried past them. |

**Root cause was never identified.** Working theory (unconfirmed, and the 6 h pause result argues
against the simplest version of it): an orphaned-request backlog building up server-side.
Don't spend time re-litigating this — go straight to `--parallel 2`.

**The recurring false alarm:** every ~24 h, `--budget-s 86400` runs out and the wrapper's
`while true` loop restarts the python worker. In the last 1–2 h before that boundary, the
rejection rate spikes sharply (seen as high as 70% again) as the script races through whatever
remains of the job queue — `budget exhausted; will resume next run` responses come back near
instantly, so the loop burns through many months' worth of submissions in minutes. **This looks
identical to the original severe-rejection problem and is not one.** It clears on its own once
the fresh worker starts its own 24 h budget. Check the process start time (`ps -o etime`) before
treating a rejection spike as news — if it's within ~1–2 h of a 24 h multiple since the last
restart, it's probably this.

## Atomic writes are not optional for resumable state

`State.write_members()` used to `xr.open_dataarray(p).load()` without closing the handle, then
write the same path. Two failure modes from the one bug:

- **Same-process**: the second month's write in one run hit a stale handle and crashed —
  looked like a "zombie" process because `ThreadPoolExecutor`'s `atexit` drains the pre-submitted
  fetch queue even after the main thread has died.
- **Cross-process**: a concurrent `pull_status.py` (or any other read) racing the live pull's
  write zeroed out a real index file (`state/members/ecmwf/19/forecast_idx.nc` → 0 bytes),
  recovered only because a checkpoint existed.

Fix (now in place): temp file + `Path.replace()`, so a reader always sees the old complete file
or the new one, never a partial write. **Any future script that reads-modify-writes a shared
state file on disk should do this from the start** — it is cheap and the alternative cost a real
data-loss incident mid-pull.

## GRIB retention paid for itself

Keeping raw GRIB locally (`state/grib/`, gitignored) rather than deleting after decode cost
~130 GB of a 468 GB disk — never close to a constraint — and is what made the corruption
recovery above possible without re-pulling. Keep doing this for any pull that isn't obviously
disk-bound.

## `--dry-run` only *prints* the first 2 jobs — don't mistake that for the total

`pull_s2s.py --dry-run` logs one line with the true totals —
`N jobs (M requests) planned, K requests to fetch` — and then prints the **first two jobs'**
individual requests as a human-readable sample. Reading only the sample (e.g. piping through
`head` or `tail`) gives a wildly wrong picture of remaining scope; this happened once mid-pull
and produced a bad ETA. Always grep for the summary line (`grep "jobs (.*requests) planned"`)
rather than counting printed request lines.

## Monitoring pattern that worked

- Rejection rate **since the current worker's restart**, not since the dawn of time:
  `awk -v s="<restart timestamp>" '$0 >= s' logs/pull_history_s2s.log | grep -c "rejected:"` vs
  `grep -c "submitted s2s-"`. Stale pre-restart lines otherwise skew the rate.
- To tell "stalled" from "genuinely slow" during a quiet stretch: CPU time via `ps -o time=`
  sampled a few seconds apart, plus `ss -tnpi` for live bytes on the TCP connections. A process
  with flat CPU and no live sockets is stuck; one with live sockets and non-zero `bytes_received`
  is just waiting on a slow ECDS response (this happened, resolved on its own both times).
- 20-minute check cadence was about right: frequent enough to catch a real problem quickly,
  infrequent enough not to be noise.

## For next time (and for `ecmwf-haul`)

1. Start at `--parallel 2`. Don't rediscover the 4→1→2 trial-and-error.
2. Don't bother with a multi-hour "let it cool down" pause on a rejection spike — it didn't work
   once, and the budget-boundary explanation (see above) accounts for most of what looks alarming.
3. Check the rejection rate against the current worker's start time before reacting to it.
4. Any puller that keeps resumable on-disk state: atomic writes (temp file + rename) from day one.
5. Keep raw GRIB on disk unless space is actually tight.
6. A future downloader should default to a **steady, moderate submission rate** rather than
   maximum parallelism — ECDS's rejection behaviour here looked like it was punishing sustained
   load/bursts, not total volume, which is the opposite of what you'd naively optimise for.
