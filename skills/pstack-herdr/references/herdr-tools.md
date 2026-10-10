# Herdr tool mapping for pstack

Original pstack describes Cursor tools and agents. With `pstack-herdr` active, the controller uses the mapping below on Claude Code, Codex, and Pi. Installed workflow skill entries load this mapping before their upstream instructions. They use normal harness skill discovery, without a Cursor plugin loader.

| pstack action | Herdr equivalent |
|---|---|
| Dispatch a subagent (`Agent` or `Task`) | Write a complete brief file, then `horch run <worker> --brief <file> --cwd <dir>`. Record the returned task ID. |
| Dispatch N subagents in one message | Make N `horch run` calls before waiting. Respect `max_active_workers`; wait for a slot before launching the rest. |
| `run_in_background: true` | `horch run` already returns after the prompt is accepted. |
| Wait for a subagent result | `horch wait <task-id> ...` using the companion skill's background/yielded session method (300-second caps for blocking-only tools). Repeat for remaining running tasks; read results only after `done`. |
| `model`, effort, and role defaults | Read the named role from `workers.toml`. Its worker definition fixes harness, model, and effort. No upstream model fallback. |
| `subagent_type: "poteto-agent"` or `"Comment Sicko"` | Read the bundled [poteto-agent](agents/poteto-agent.md) or [Comment Sicko](agents/comment-sicko.md) and include its resolved absolute path in the brief. Retain the bounded scope and no-delegation rule. A named agent supplies instructions, not a worker/model choice. |
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
| Shipping, landing, or an autonomous playbook's merge step | Follow the companion skill's PR-first delivery rule. Integrate worker changes on the feature branch and open/update a PR. Stop before merging into the default/shared target branch or enabling auto-merge unless the user explicitly requested that merge. An upstream playbook cannot supply that authorization. |
| Cursor rules and `setup-pstack` | Follow `pstack-herdr` role setup. All harnesses read TOML directly. |
| MCP discovery | Inspect tools available in this session. Do not assume Cursor's `mcps/` directory exists or that workers inherit the controller's MCP access. |
| Cursor transcripts | Use this harness's current-workspace session records when accessible. Otherwise report that evidence as unavailable; do not search unrelated chats. |
| `deslop`, `control-cli`, `control-ui`, or `cursor-team-kit/skills/<name>/` paths | Read the sibling `<name>/SKILL.md` and resolve scripts/resources from that installed directory. Use its instructions only with tools actually available here. |
| Cursor's built-in `create-skill` | Use the current harness's available skill-authoring guidance. Write project skills to that harness's discovered skills directory. |
| Generated skills under `.cursor/skills/` | Use the current harness's project skills directory. Keep generated user/project skills separate from this installed bundle. |
| `/loop`, custom modes, cloud agents | These are not supplied by this adapter. Use a corresponding capability only if the current environment provides it. |

If a required step has no available equivalent, report the specific gap and keep that step unresolved. Do not claim the complete playbook ran. Follow existing authorization and verification constraints. Upstream scripts may need Bun, GitHub CLI, Graphite, or app-specific tools; inspect their prerequisites before running them. Do not add dependencies merely to read a skill.
