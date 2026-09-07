# Decisions

Every choice made while scaffolding this repository that the spec (`docs/scaffold-prompt.md`) did
not specify. Recorded so a reviewer can tell a deliberate decision from an accident.

---

## Where a container was tempting, and what was done instead

The no-Docker constraint is a hard project rule. Three places where reaching for one would have
been the reflex:

1. **A local Postgres for verifying gold SQL.** Every `gold_sql` in
   `eval/datasets/core_vi/questions.jsonl` had to be *executed*, not guessed. The obvious move is
   `docker run postgres`. Instead, `db/seed.py` accepts any SQLAlchemy URL and transpiles
   `db/schema.sql` with sqlglot, so a throwaway **SQLite** file in the git-ignored `data/`
   directory serves the same purpose with no daemon at all. All five gold queries were executed
   against it before being committed; the row counts are recorded in each item's `notes`.
2. **A Postgres service container in CI.** `test_readonly_role.py` genuinely needs a live
   database. Rather than adding a `services:` block, that file **skips with an explicit message**
   and the CI report shows the skip. A visible skip is more honest than a green tick that proves
   nothing.
3. **Self-hosted Langfuse for tracing.** Its topology is Docker Compose (Postgres + ClickHouse +
   Redis + MinIO). Replicating it under systemd is disproportionate. Tracing writes to a plain
   `agent_traces` table in the same Postgres; Langfuse **Cloud** is optional enrichment.

`.github/workflows/ci.yml` fails the lint job on container tooling that is actually **used**: it looks for
artefacts (`Dockerfile*`, `docker-compose*.yml`, `.devcontainer`, `.dockerignore`) and for
invocations (`docker run|build|compose|…`, `kubectl `, `helm install|upgrade|template`). It
deliberately does **not** grep for the bare word — the first version did, and it failed on the
comments explaining the constraint, including its own. A check that fires on prose about a rule
rather than on violations of it teaches people to disable the check.

**CI moved from GitLab CI to GitHub Actions** once the repository actually landed on GitHub
(`github.com/nhatm2400/viet-text2sql-agent`). The pipeline stages are unchanged
(`lint → test → security → deploy`); only the syntax and the secret names differ. This was not a
preference — a `.gitlab-ci.yml` on a GitHub remote simply never runs, which would have made the
proposal's claim that "the security suite runs as a distinct CI job" **false in practice**. The
proposal and both README languages were corrected rather than left aspirational.

One incidental improvement: **GitHub-hosted runners are virtual machines, not containers**, so
the honest caveat the GitLab version needed — that GitLab's shared runners execute jobs inside
containers on GitLab's infrastructure — no longer applies. There is now no container anywhere in
the loop, not even one owned by someone else.

---

## Dependencies and packaging

| Decision | Reasoning |
|---|---|
| Version ranges in `pyproject.toml`, exact pins in `requirements.lock` | The spec asked for exact pins. Hard-pinning in `pyproject` breaks installs whenever a transitive constraint moves; the lock file (`make lock`) carries the exact set that was actually tested. |
| `pip` + venv, not `uv` | `uv` is the spec's first choice but was not installed on the machine, and the spec forbids installing anything unasked. The fallback (pip with a pinned lock) is the documented alternative. `make venv` uses whichever is present. |
| `langchain-anthropic` / `-openai` / `-aws` are **not** dependencies | The offline path must install and run without any provider SDK. They are imported lazily in `llm/provider.py`; a missing one raises an install hint, not a traceback. |
| `hatchling` build backend, `src/` layout | Needed for `pip install -e .` to expose `t2sql` without a `sys.path` hack in every entry point. |
| No `__init__.py` under `eval/` | `python -m eval.harness.runner` works via PEP 420 namespace packages. Adding init files would have meant adding files the target tree does not list. |

---

## Architecture

**`ToolResult` in `tools/__init__.py`.** The spec did not define a shared tool return type. Every
tool returns the same Pydantic shape (`status`, `message`, `data`, `error_kind`) because the trace
store writes `result` as JSONB and the agent needs a machine-readable status to choose a recovery
strategy. Free-text error strings would make that decision guesswork.

**`ast_policy` imports `schema_tools.load_schema()` (lazily).** Architecturally backwards —
guardrails depending on tools — but the alternative was duplicating the schema parser, and two
parsers that can disagree about which columns exist is a worse security property than one
slightly awkward import. There is no cycle: `schema_tools` imports nothing from `guardrails`.

**Tracing split.** A wrapper in `agent/build.py` traces every tool; `execute_sql` opts out via
`metadata={"self_logs": True}` and writes its own audit row next to the policy check. Rationale:
the audit log is part of the security guarantee, so it belongs with enforcement rather than with
the graph — and double-logging would corrupt the tool-calls-per-question metric.

**`tracing.current_trace_id` is a `ContextVar`.** Tool wrappers need the run's trace id without
threading it through every tool signature. A ContextVar (not a module global) keeps concurrent
FastAPI requests from cross-writing each other's traces.

**Custom nodes around LangGraph's prebuilt `ToolNode`.** `ToolNode` executes the tools; a thin
wrapper node increments `iteration_count`, and the conditional edges own both stop conditions.
Keeping the cap in a plain routing function — rather than inside a tool or a callback — is what
makes it auditable in about ten lines.

**`recursion_limit = 2 * cap + 4`.** LangGraph's own runaway guard, set deliberately looser than
the project's cap so the project's cap is always what fires. If the recursion limit ever throws,
that is a bug in the routing edge, not a tuning problem.

**`summarise()` is a pure function over the message list**, not extra graph state. Deriving the
result at the end keeps `AgentState` small and means the API, the eval harness and the demo all
read the run the same way.

---

## Security decisions the spec left open

| Decision | Reasoning |
|---|---|
| `SELECT *` blocked when a sensitive-column table is in scope | A star projection returns `customers.email` without ever naming it. `SELECT * FROM regions` still passes — the rule is targeted, not blanket. |
| `COUNT(*)` explicitly exempted | A star inside an aggregate returns no column values. Blocking it made `q004` fail; the fix is narrow (star whose parent is a function). |
| Sensitive columns denied in `WHERE`, not just the projection | `WHERE email = 'x'` is an oracle: repeated queries enumerate the column one guess at a time. |
| Comment smuggling = any `;` or DDL/DML keyword inside a comment | Strict, and it can reject a harmless comment. Accepted: comments carry no analytical value in generated SQL. String literals are excluded by a hand-written scanner, so `WHERE channel = 'we--b'` still works. |
| Unconstrained `JOIN` blocked, including explicit `CROSS JOIN` | An intentional cross join is indistinguishable from an accidental one at this layer, and `orders × products` is 6M rows. |
| `max_joins = 6` | Sized to the schema: the widest legitimate seed query uses 4. Documented as a heuristic in `docs/SECURITY.md`. |
| Blocked queries return HTTP 200 | A 4xx would make "the policy worked" indistinguishable from "the request was malformed" in every client and in the demo UI. |
| No auth on the API | Non-goal per the proposal. The read-only role is the access-control boundary, and that is stated rather than implied. |

---

## Evaluation decisions

**Offline `execute_sql` replays recorded result sets, it does not skip the policy.** The AST check
runs in full; only the database driver is replaced by a lookup in
`tests/fixtures/offline_sql.json`. Without this, `make demo-offline` could not show a final
answer or a chart — and, more importantly, the bypass test would not be exercising the offline
path that CI actually runs.

**Fixture result sets are recorded from the real seeded snapshot**, never hand-written. Invented
numbers in a fixture are indistinguishable from measured ones once they reach a summary table.
Regenerate after changing `db/seed.py`, `db/schema.sql`, any gold SQL, or the LLM script:

```bash
python db/seed.py --url sqlite:///data/dev.sqlite    # data/ is git-ignored
# then re-record: for every execute_sql arg in tests/fixtures/offline_llm.json and every
# gold_sql in eval/datasets/core_vi/questions.jsonl, run check_sql(), execute both the raw and
# the policy-rewritten form, and write {sql, columns, rows} into tests/fixtures/offline_sql.json
```

**`q003`'s fixture deliberately predicts an extra column.** The offline smoke run therefore
reports **strict 80% / relaxed 100%** rather than a clean 100/100. A scoring harness whose two
metrics never disagree has not been shown to distinguish them.

**Relaxed matching tries name → position → value, and stops at 8 columns.** The value search is
`O(n!)`; above `MAX_PERMUTATION_COLUMNS` it is skipped and the reason is recorded, so a
skipped search is never silently reported as a failed match.

**Metrics return `None`, never `0.0`, for an empty denominator.** "0% self-correction" and "no
item needed self-correction" are different statements, and `metrics.py` adds an explicit note
when a rate is undefined.

**The five seed questions are ordinary analytics questions with glossary traps**, not puzzles:
`doanh thu` (payments vs orders), `miền` (customers.region_id vs addresses), cancelled orders
(`created_at` vs the always-NULL `completed_at`). Each item's `notes` names the trap.

**`q004` says "trạng thái active" rather than "khách hàng active".** The bare phrase is an
unverified glossary term needing a recency window; it belongs in the deliberately ambiguous slice
that measures clarification rate, not in an item with a gold answer. The fixture question
"Có bao nhiêu khách hàng active?" exercises that path via `ask_clarification`.

**Seed volume: 5,000 customers / 20,000 orders / 49,792 order_items.** Under the ≤50k budget with
no rounding down of realism.

**A `paraphrase/pairs.jsonl` scaffold with a `_comment` schema line**, loaded and skipped by the
runner. An empty file would not communicate the shape.

---

## Deployment decisions

| Decision | Reasoning |
|---|---|
| One hostname, path-based split (`/api/*` → FastAPI, `/` → Streamlit) | One DNS record and one tunnel route to keep in sync with the tenten.vn zone. Cost: the `handle_path` prefix strip. |
| `auto_https off` in Caddy | TLS terminates at the Cloudflare edge. Caddy cannot solve an ACME challenge for a host that has no inbound port. |
| Both services bound to `127.0.0.1` | The tunnel plus Caddy is the only ingress; the firewall can deny all inbound except SSH. |
| systemd hardening (`ProtectSystem=strict`, `NoNewPrivileges`, …) | Cheap, and it substitutes for the isolation a container would otherwise have provided. |
| `provision.sh` refuses to run without `DB_APP_PASSWORD` / `DB_RO_PASSWORD` | A provisioning script that invents a default password is a provisioning script that ships one. |
| `keepalive_ping.py` restarts via `systemctl`, not just pings | systemd's `Restart=on-failure` covers a crashed process. It cannot see a process that is alive but wedged; this can. |
| Nightly `pg_dump`, 7-day rotation | Enough to recover a demo. Explicitly not a production backup, and said so in the README. |

---

## Not done, and why

- **Retrieval (`retrieval/*`, `search_examples`)** — typed stubs raising `NotImplementedError`
  with a pointer. It is a hypothesis under test (ablations A2/A3), and the one piece of direct
  Vietnamese evidence available reports schema filtering *underperforming* plain few-shot. A
  half-working version would contaminate the baseline it is meant to be compared against.
- **Vietnamese time-expression resolution** — stubbed. The hard part is not parsing "quý trước";
  it is that fiscal quarters, "tháng này" mid-month and "cùng kỳ năm ngoái" need an agreed
  convention with the business before any of them can be called correct.
- **The repair loop's internals** — the agent already retries after a failed `execute_sql` (the
  offline demo shows it); the *bounded, configurable* repair of ablation A4 is not built.
- **`glossary.yaml` has 3 verified terms and 15 TODO keys.** Unverified entries are excluded from
  the system prompt entirely: a wrong mapping the agent trusts is worse than no mapping.
- **External dataset downloads** — scripts print their licence and exit. Neither was executed,
  and both `VERSION_TAG`s are unpinned placeholders that must be pinned before any reported run.

---

## Repository changes outside the target tree

`PROPOSAL.md` and `scaffold-prompt.md` were at the repository root when scaffolding began. Both
were **moved** (not deleted) into `docs/`, where the target tree places `PROPOSAL.md`. Nothing was
deleted at any point.
