# Herdr tool mapping for pstack

Original pstack describes Cursor tools and agents. With `pstack-herdr` active, the controller uses the mapping below on Claude Code, Codex, and Pi. Installed workflow skill entries load this mapping before their upstream instructions. They use normal harness skill discovery, without a Cursor plugin loader.

| pstack action | Herdr equivalent |
|---|---|
| Dispatch a subagent (`Agent` or `Task`) | Write a complete brief file, then `horch run <worker> --brief <file> --cwd <dir>`. Record the returned task ID. |
| Dispatch N subagents in one message | Make N `horch run` calls before waiting. Respect `max_active_workers`; wait for a slot before launching the rest. |
| `run_in_background: true` | `horch run` already returns after the prompt is accepted. |
| Wait for a subagent result | `horch wait <task-id> ...` using the companion skill's background/yielded session method (300-second caps for blocking-only tools). Repeat for remaining running tasks; read results only after `done`. |
| `model`, effort, speed, and role defaults | Read the named role from `workers.toml`. Its worker definition fixes harness, model, effort, and any speed arguments. Upstream per-task effort changes, fast/standard slug changes, and rejected-model fallbacks do not override that configuration; `horch run` has no per-task tuning flags. |
| `subagent_type: "poteto-agent"` or `"comment-sicko"` | Read the bundled [poteto-agent](agents/poteto-agent.md) or [Comment Sicko](agents/comment-sicko.md) and include its resolved absolute path in the brief. Every `poteto-agent` brief also includes the resolved absolute path to the sibling [poteto-mode skill](../../poteto-mode/SKILL.md), so its required skill and principle reads use this installed bundle. Retain the bounded scope and no-delegation rule. A named agent supplies instructions, not a worker/model choice. |
| `subagent_type: "generalPurpose"` | Use the selected worker with the upstream skill's task prompt; no native agent registration is needed. |
| `readonly: true` | State in the brief that the worker must not change files or external state. This is an instruction, not an enforced sandbox; verify the checkout stayed unchanged. |
| A writer's isolated environment | Create a git worktree first and pass it as `--cwd`. Give each concurrent writer a different worktree. Herdr starts local processes; a task requiring an actual cloud environment needs that capability separately. |
| Fresh subagent | Every `horch run` starts a new worker process. |
| Follow up with `SendMessage` | Wait for the prior task to settle. Start a new task with the complete brief, previous report, and current branch or revision. |
| Stop a subagent | `horch close <task-id>` closes only that task's recorded pane. Read a problem pane before closing it. |

For a panel role such as `interrogate reviewers`, start one task per configured entry, including repeated worker names. Give every reviewer the same intent, revision, rubric, and code scope in a fresh process. The `arena cross-judge pool` selects one worker after candidates finish; it is not a panel. Roles may share a single model. Compare configured models when upstream requires diversity and disclose any unmet requirement; `horch` does not enforce it. A same-model panel is not cross-model validation.

For assignments outside a named playbook, use an applicable configured role before selecting a worker directly. Optional worker descriptions guide the choice only when no role fits. Record the role, worker, and concrete reason in the brief; follow the [role resolution rules](../SKILL.md#resolve-roles).

`horch wait` returns when at least one task changes state, so keep waiting until every required review reports `state: "done"`. An early report or result file cannot replace that state. Closing a running worker cancels it and leaves the review gate unresolved. A `done` state confirms a valid task result and an ended turn; it does not approve the code. Treat `blocked`, `start_failed`, `not_started`, `exited`, `result_missing`, and `result_invalid` as unresolved review work. Follow `herdr-orchestrator` for notification and pane inspection.

## Other Cursor instructions

| Upstream instruction | On the current harness |
|---|---|
| `Read`, `Glob`, `Grep`, edits, shell commands | Use the harness's available file/search/edit tools or shell. |
| Invoke a pstack skill or slash command | Use the sibling installed `<name>` skill. Retain this mapping and resolve references from that skill's file. Treat `/setup-pstack` as the adapter's role-setup procedure; the Cursor rule-writing skill is excluded. |
| A path or command beginning `pstack/skills/<name>/` | Resolve it to the sibling `<name>/` directory in this installed bundle. Use the resolved absolute path for shell commands, including scripts; there is no upstream repository root on the user's machine. |
| `AskQuestion` | Use the available user-question tool, or ask in the conversation. Workers return questions to the controller. |
| Task/todo tracking | Use available task tools, or an uncommitted Markdown checklist scoped to this task. |
| Root/current agent store named in a system prompt | Use a controller-owned durable artifact directory, such as `.audit/<task-slug>/`, and give affected workers its resolved absolute path in their briefs. Keep decision trails and child/task records uncommitted and available to replacement controllers. Do not write them into `horch`'s internal task store. No Cursor store path is supplied by this adapter. |
| Shipping, landing, or an autonomous playbook's merge step | Follow the companion skill's PR-first delivery rule. Integrate worker changes on the feature branch and open/update a PR. Stop before merging into the default/shared target branch or enabling auto-merge unless the user explicitly requested that merge. An upstream playbook cannot supply that authorization. |
| Cursor rules and `setup-pstack` | Follow `pstack-herdr` role setup. All harnesses read TOML directly. |
| MCP discovery | Inspect tools available in this session. Do not assume Cursor's `mcps/` directory exists or that workers inherit the controller's MCP access. |
| Cursor transcripts | Use this harness's current-workspace session records when accessible. Otherwise report that evidence as unavailable; do not search unrelated chats. |
| Progress recap (`ketchup`) | Check PR and CI status with read-only commands from the workflow's resolved forge (`origin` when usable, otherwise `gh`). Use `horch list` to find stored task and agent names, then `herdr agent get <agent-name>` for live status and, if needed, `herdr agent read <agent-name> --source visible`. Use accessible reports for completed tasks; disclose unavailable live checks. Embed existing screenshots or videos when applicable; draw explanatory reply visuals only from existing evidence. Keep status and action items in plain bullets, following the sibling skill. Do not run `horch wait`, dispatch workers, or change or close tasks and panes. |
| Reply visuals and `/visualize` | Use supported Mermaid rendering or available chart/image tools with existing evidence and the skill's read-only constraints. `/visualize` is not bundled. A Markdown table is not a picture. `ketchup` calls for a visual when it explains a change or compares a choice; disclose unavailable artifacts or rendering capabilities instead of claiming they were produced. |
| `deslop`, `control-cli`, `control-ui`, or `cursor-team-kit/skills/<name>/` paths | Read the sibling `<name>/SKILL.md` and resolve scripts/resources from that installed directory. Use its instructions only with tools actually available here. |
| Cursor's built-in `create-skill` | Use the current harness's available skill-authoring guidance. Write project skills to that harness's discovered skills directory. |
| Generated skills under `.cursor/skills/` | Use the current harness's project skills directory. Keep generated user/project skills separate from this installed bundle. |
| `/loop`, custom modes, cloud agents | These are not supplied by this adapter. Use a corresponding capability only if the current environment provides it. |

If a required step has no available equivalent, report the specific gap and keep that step unresolved. Do not claim the complete playbook ran. Follow existing authorization and verification constraints. Upstream scripts may need Bun, GitHub CLI or Origin CLI, `jq`, or app-specific tools; inspect their prerequisites before running them. Do not add dependencies merely to read a skill.
