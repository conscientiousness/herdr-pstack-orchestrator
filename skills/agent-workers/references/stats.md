# Worker statistics

Use `agent-workers stats` when the user asks whether workers are worth keeping, slow,
failing, or efficient, whether reminder timing fits, or before changing
`workers.toml`. It reports facts; the controller interprets them.

```bash
python3 <skill-dir>/scripts/agent-workers.py stats [--workspace <id>] [--days <n>]
```

This reads only workers.toml and the task store: no Herdr calls, environment
requirement, locks, or writes. The default is the whole store because worker
definitions are global. Workspace scope uses the recorded launch workspace;
positive integer days filter created_at from a UTC cutoff (inclusive).
Concurrent controllers can change records during the scan; it is not a snapshot.

## Fields

- `scope` records filters and cutoff; `task_count` totals valid in-scope records.
- `workers` is keyed by names seen in scope or currently configured.
  `configured`, `harness`, `model`, `effort`, `provider` describe current configuration,
  not necessarily the model used for historical tasks; arguments are omitted.
- `task_count`, `states`, `result_statuses`: stored task states and valid,
  nonce-bound result statuses, only delivered (`done`) results for the latter.
  Early, missing, and invalid results are not counted as delivered outcomes.
- Closed tasks whose stored state is not settled count as `states.closed_before_done` (cancellations), not `running`; closed settled tasks keep their outcomes.
- `unclosed_running` counts in-flight work separately. `problem_count` counts only
  settled problem states; `problem_rate` divides by done + problems, excluding
  running and cancellations. No settled outcomes means null, not zero.
- `last_use` is the latest created_at; `workspaces` counts recorded workspace IDs.
  Legacy records contribute to `unknown_workspace_count`, not workspace filters.
- `duration_minutes`: sample_size, median, nearest-rank p90, max, and `sources`
  counts for done tasks with valid results (any result status). Prefer the first
  observed `first_done_at` in state.json; legacy records use result.json mtime.
  `duration_samples` identifies each task's minutes and `endpoint_source`.
  `duration_excluded_count` counts done records without usable results/timing.
  Negative/future endpoints and malformed timestamps are excluded.
- `configured_unused_workers` lists configured names with zero tasks in scope;
  `roles_with_unconfigured_workers` maps roles to missing assigned names.
- `invalid_task_ids` lists malformed task/state records excluded from numbers.
  Known raw workspace/date metadata narrows invalid-record scope; unknown scope
  remains visible. Missing task/state files during publication/removal are skipped.
- `reminder_fired` counts in-scope tasks with stored `long_notified: true`, per
  worker and in total; unlike the delivered-duration estimate, this flag records
  only reminders where a `wait` observed the task past the threshold configured
  at that time.
- `delivered_duration_estimate` gives timed_task_count and count/share strictly
  above the configured reminder threshold (`current`) and 15/30/45/60/90 minutes
  (`thresholds`, excluding current). This estimates delivered-duration tails,
  not reminder firings or active elapsed times. Empty rates/percentiles are null;
  empty counts are zero.

## Interpretation and configuration

Small samples can mislead; different task scopes are not controlled comparisons.
A blocked result may be a real specification question. Provider faults behind
result_missing are not evidence of poor model behavior. Durations include startup,
notification/polling delays and any wait for observation; mtime fallback can shift
if results are copied or rewritten. `settled_at` retains first settlement even
on problems; `first_done_at` independently retains first delivery after recovery.
Observation and mtime samples are mixed: trends across this source switch are not
strictly comparable.
The store cannot show reviewer quality or cost.

Knobs are `notify_after_minutes`, removing or redefining a worker, role assignments,
and `max_active_workers` (per-workspace concurrency, not worker speed). The user owns
workers.toml: propose changes with the numbers and edit only with consent, because
these choices affect their routing, resources, and authorization.
