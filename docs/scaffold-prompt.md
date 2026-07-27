# MISSION — Scaffold `viet-text2sql-agent`

You are a senior Python platform engineer. In the **current empty folder**, create the complete repository skeleton for a bilingual (Vietnamese question → English schema) Text-to-SQL analytics agent, plus ONE thin vertical slice that runs end-to-end **offline** (no API keys, no database). This session delivers scaffolding only.

## Context (locked decisions — do not revisit)

- Positioning: a **data-reliability & evaluation** project. The evaluation harness exists BEFORE the agent is optimized.
- Architecture: a genuine **ReAct tool-calling agent** in LangGraph — one LLM node loops, calling tools and deciding the next action itself (retry, ask the user, or finish). This is NOT a fixed linear pipeline. Tools: `list_schema`, `get_table_schema`, `lookup_glossary`, `search_examples`, `validate_sql`, `execute_sql`, `propose_chart`, `ask_clarification`.
- **Autonomy is bounded, policy is not agent-controlled:**
  - Hard `max_iterations` (default 6) — graph forcibly terminates with a structured "could not complete safely" result if exceeded. This is a MANDATORY stop condition.
  - `execute_sql` unconditionally re-runs the full AST + read-only checks internally — it NEVER trusts that the agent already called `validate_sql`. The agent chooses strategy; it never gets to choose whether policy applies.
  - `ask_clarification` is a first-class tool: on ambiguous questions the agent can stop and ask instead of guessing.
- Defense in depth for SQL, enforced inside tool implementations (not by prompting the agent to behave):
  1. Postgres **read-only role** (`t2sql_ro`) with SELECT-only grants and a default `statement_timeout`
  2. **sqlglot AST policy** (single statement, SELECT-only, allowlists, LIMIT enforcement) — lives inside `execute_sql`, always runs
  3. **Execution wrapper** (read-only connection, row cap, error wrapping)
- Charts are **declarative JSON specs** validated by Pydantic against an allowlist and rendered with Plotly. NEVER execute model-generated code anywhere in this project.
- Scoring: **strict AND relaxed execution accuracy**, implemented as pure functions and unit-tested with fabricated result sets — no LLM involved.
- `OFFLINE_MODE=1` swaps every LLM call (including tool-call decisions) for a deterministic fixture provider that replays a scripted sequence of tool calls (fixtures in `tests/fixtures/`). CI and the demo slice MUST pass with no keys and no network and no database.
- External datasets (ViText2SQL, Spider, BIRD) are NEVER committed — download scripts plus license notes only. ViText2SQL license: research/education only, no redistribution in any form.
- **NO DOCKER, ANYWHERE — this is a hard constraint, not a preference.** Not locally, not in CI, not on the deploy target. Everything runs as plain OS processes:
  - Postgres 16 + pgvector installed via the PGDG apt repository (`postgresql-16-pgvector` — prebuilt package, no compilation required).
  - The app runs under `systemd` via `uvicorn`; Streamlit runs under its own `systemd` unit.
  - **Caddy** as reverse proxy (single static binary, automatic HTTPS) — no nginx-in-a-container.
  - **`cloudflared`** as a native binary + systemd service for tunnel exposure (it was never Docker-dependent, so this is unaffected by the no-Docker constraint).
  - **Kubernetes is explicitly out of scope.** It is still fundamentally a container orchestrator, which contradicts "no Docker." Do not suggest it, do not scaffold for it.
- **Tracing is self-built in Postgres, not Langfuse self-host.** Langfuse's self-host design assumes Docker Compose (Postgres + ClickHouse + Redis + MinIO); replicating that by hand via systemd is disproportionate effort here. Instead, `observability/tracing.py` writes every tool call (name, arguments, result, latency, token count if available) to a plain table `agent_traces` in the same Postgres database, and the Streamlit app has a "Traces" tab reading from it. If `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` env vars are present, ALSO send events to Langfuse Cloud (SaaS, free tier, zero install) as an optional richer view — never required for the app to function.
- **CI/CD is GitLab CI, deploying over SSH — no image build, no registry.** `.gitlab-ci.yml` stages: `lint` → `test` (offline, no DB, no network) → `security` (red-team suite, offline) → `deploy` (main branch only: SSH into the VPS using a CI/CD variable holding a deploy key, `git pull`, `uv sync` / update the venv, `systemctl restart t2sql-api t2sql-ui`). GitLab's own shared runners execute inside containers on GitLab's infrastructure — the developer never installs, configures, or touches Docker themselves; this is orthogonal to the no-Docker constraint above, which is about the developer's machine and the deploy target.
- **Local development needs only a Python venv — no local Postgres either.** `make test`, `make lint`, and `make smoke` run against offline fixtures with zero database or network dependency. For manual interactive testing (a live database), do NOT attempt to install Postgres+pgvector on Windows (pgvector needs a C build toolchain there and is fragile); instead connect over an SSH tunnel to a `dev` database that lives on the VPS (`ssh -L 5432:localhost:5432 user@vps`, then point `DATABASE_URL` at `localhost:5432`). The Windows machine only ever needs Python and an editor.

## Hard rules

- NEVER add dependencies, files, features, or abstractions beyond this spec. Only what is directly requested.
- NEVER add Docker, docker-compose, Dockerfiles, devcontainers, or any containerization — even "just for convenience" or "just for local dev." If you believe a container would help, say so in `docs/DECISIONS.md` and do NOT add it.
- NEVER hardcode secrets. `.env.example` contains variable names and comments only.
- NEVER commit: data files, `eval/results/*` contents, `.env`, or anything under `data/`.
- NEVER implement full retrieval, repair-loop internals, or Vietnamese time-expression resolution in this session — stub these with typed signatures, docstrings, and `# TODO(phase2):` markers. Stubs raise `NotImplementedError` with a helpful message, except where the vertical slice needs a trivial pass-through.
- ASK ME before: installing anything not in the stack list, deleting any file, or running any destructive terminal command.

## Step 1 — Plan artifact first

Before writing any code, produce an implementation-plan artifact containing: the target tree below (verbatim), your ordered task list, and the acceptance checklist from "Done when". **Pause for my approval before executing.**

## Stack (pin exact versions in pyproject + lockfile)

Python 3.11+, FastAPI, LangGraph + langchain-core, SQLAlchemy 2 + psycopg[binary], sqlglot, Pydantic v2 + pydantic-settings, Plotly, Streamlit, PyYAML, pytest, ruff. Package manager: `uv` (fallback: pip with a pinned requirements lock). Deploy-time only (not Python deps): PostgreSQL 16 + pgvector (PGDG apt), Caddy, cloudflared. Assumes model-provider keys arrive via environment variables only.

## Target repository tree (create exactly this; no extra top-level items)

```
viet-text2sql-agent/
├── README.md
├── Makefile
├── pyproject.toml
├── .env.example
├── .gitignore
├── deploy/
│   ├── provision.sh                   # VPS setup: apt install postgresql-16, postgresql-16-pgvector, caddy, cloudflared
│   ├── Caddyfile                      # reverse proxy config, one block per service
│   ├── systemd/
│   │   ├── t2sql-api.service          # uvicorn unit
│   │   └── t2sql-ui.service           # streamlit unit
│   └── cloudflared/
│       └── README.md                  # tunnel setup instructions (token via env, never committed)
├── docs/
│   ├── PROPOSAL.md                    # provided separately; leave a placeholder note
│   ├── DECISIONS.md                   # every choice you made that this spec did not specify
│   └── SECURITY.md                    # threat model + policy summary
├── src/t2sql/
│   ├── __init__.py
│   ├── config.py                      # pydantic-settings
│   ├── llm/
│   │   └── provider.py                # anthropic | openai_compatible | bedrock | offline
│   ├── agent/
│   │   ├── state.py                   # AgentState: messages, iteration_count, trace_id
│   │   ├── build.py                   # LangGraph: agent node ⇄ ToolNode loop, max_iterations edge
│   │   └── prompts.py                 # system prompt: schema block, glossary, tool-use instructions
│   ├── tools/
│   │   ├── schema_tools.py            # list_schema, get_table_schema — IMPLEMENT (reads schema.sql metadata)
│   │   ├── glossary_tools.py          # lookup_glossary — stub, reads db/glossary.yaml
│   │   ├── retrieval_tools.py         # search_examples — stub (pgvector)
│   │   ├── validate_tool.py           # validate_sql — thin wrapper over guardrails.ast_policy
│   │   ├── execute_tool.py            # execute_sql — IMPLEMENT FULLY (always re-validates, read-only, timeout, row cap)
│   │   ├── chart_tool.py              # propose_chart — thin wrapper over charts.spec
│   │   └── clarify_tool.py            # ask_clarification — halts the loop, returns to caller
│   ├── guardrails/
│   │   ├── ast_policy.py              # IMPLEMENT FULLY
│   │   └── policy.yaml                # allowlists, sensitive columns, limits
│   ├── retrieval/
│   │   ├── store.py                   # pgvector interface (stub)
│   │   ├── glossary.py                # stub
│   │   └── examples.py                # verified few-shot store (stub)
│   ├── charts/
│   │   └── spec.py                    # Pydantic ChartSpec + plotly renderer
│   ├── api/
│   │   └── main.py                    # FastAPI: POST /ask, GET /health
│   └── observability/
│       └── tracing.py                 # writes to Postgres agent_traces table; optional Langfuse Cloud forwarding
├── db/
│   ├── schema.sql                     # 12-table EN e-commerce schema
│   ├── roles.sql                      # t2sql_ro read-only role + statement_timeout
│   ├── traces.sql                     # agent_traces table (own observability store)
│   ├── seed.py                        # deterministic synthetic data (seeded RNG)
│   └── glossary.yaml                  # VN business terms → schema mapping
├── eval/
│   ├── datasets/
│   │   ├── core_vi/questions.jsonl    # 5 verified seed items now → 80–120 later
│   │   ├── paraphrase/pairs.jsonl     # empty scaffold + schema comment
│   │   ├── security/attacks.jsonl     # 10 seed cases
│   │   └── external/                  # download scripts ONLY (no data)
│   │       ├── README.md              # licenses + version pins
│   │       ├── download_vitext2sql.py
│   │       └── download_spider_subset.py
│   ├── harness/
│   │   ├── runner.py
│   │   ├── scoring.py                 # strict + relaxed EX — IMPLEMENT FULLY
│   │   ├── metrics.py
│   │   └── report.py                  # writes summary.md
│   ├── configs/
│   │   ├── baseline.yaml
│   │   └── ablations/                 # one changed factor per file, named in a comment
│   └── results/.gitkeep               # contents gitignored
├── ui/
│   └── streamlit_app.py
├── tests/
│   ├── fixtures/                      # offline LLM fixtures
│   ├── test_ast_policy.py
│   ├── test_scoring.py
│   ├── test_readonly_role.py
│   ├── test_agent_offline.py
│   ├── test_execute_tool_bypass.py
│   └── test_max_iterations.py
├── scripts/
│   └── keepalive_ping.py              # VPS-side cron target (process/service health ping, not container-based)
└── .gitlab-ci.yml                     # lint + test + security stages (offline) + SSH deploy stage (main branch only)
```

## Component spec

### Implement fully now (small; this is the security and evaluation core)

1. `src/t2sql/guardrails/ast_policy.py` — sqlglot-based checks. Parse must succeed; exactly one statement; SELECT-only (reject all DDL/DML/DCL and `SELECT INTO`); deny `pg_catalog` and `information_schema`; table and column allowlist plus sensitive-column denylist loaded from `policy.yaml` (default deny: `customers.email`, `customers.phone`); auto-inject or clamp `LIMIT ≤ max_rows`; reject comment-smuggled extra statements. Return a structured `PolicyDecision(allowed: bool, reasons: list[str], rewritten_sql: str | None)`.
2. `eval/harness/scoring.py` — `strict_ex` (exact multiset match, column order enforced) and `relaxed_ex` (row order ignored unless gold SQL contains a top-level ORDER BY; extra predicted columns tolerated; normalization for NULL representation, float rounding, Decimal vs float, date formats). Pure functions over result sets — no database, no LLM.
3. `db/schema.sql` — 12 tables with English names: `customers, addresses, regions, categories, products, suppliers, inventory, orders, order_items, payments, shipments, reviews`; foreign keys; status enums; deliberately confusable timestamps (`created_at`, `paid_at`, `completed_at` on orders/payments). `db/roles.sql` — role `t2sql_ro`: SELECT-only on allowlisted tables, REVOKE everything else, default `statement_timeout = '5s'`. `db/traces.sql` — `agent_traces(id, trace_id, tool_name, arguments jsonb, result jsonb, latency_ms, created_at)`. `db/seed.py` — deterministic synthetic data with a fixed seed; ≈5k customers and ≤50k order rows; Vietnamese-plausible names and region values (Miền Bắc/Trung/Nam).
4. `src/t2sql/charts/spec.py` — Pydantic `ChartSpec` with `chart_type` restricted to an allowlist (`bar`, `line`, `pie`), `x`, `y`, `aggregation`, `sort`, `limit ≤ 50`; `render(spec, rows)` returns a Plotly figure; validation failure returns a structured refusal object, never an unhandled exception.
5. `src/t2sql/llm/provider.py` — `get_model(role: Literal["fast","strong"])` returning a LangChain chat model selected by env (`MODEL_PROVIDER ∈ anthropic | openai_compatible | bedrock`), plus an `OfflineProvider` that replays a **scripted sequence of tool calls** keyed by question hash when `OFFLINE_MODE=1` — this must simulate at least one multi-turn tool loop (e.g. `execute_sql` fails once → agent retries → succeeds) so the offline demo actually exercises the loop, not just a single tool call. `OfflineProvider` must not require a database connection.
6. `src/t2sql/tools/execute_tool.py` — the single most important file in this repo. `execute_sql(sql: str) -> ToolResult` MUST call `guardrails.ast_policy` internally and MUST refuse to run against the database if the policy check fails, **even if a `validate_sql` tool call already happened earlier in the same turn**. There is no code path from agent decision to database execution that skips this check. Runs on `DATABASE_URL_RO`, enforces row cap, wraps and classifies errors (syntax / permission / timeout / empty-result) so the agent can react sensibly.
7. `src/t2sql/agent/build.py` — the LangGraph loop: an `agent` node (binds all tools, one LLM call per turn) and a `ToolNode`, connected by a conditional edge that routes back to `agent` after any tool call except `ask_clarification` or a final-answer signal, and unconditionally exits after `max_iterations` turns via `state.iteration_count`. Get the stop condition right before anything else in this component.
8. `src/t2sql/observability/tracing.py` — `log_tool_call(trace_id, tool_name, arguments, result, latency_ms)` writes a row to `agent_traces` via a plain SQLAlchemy insert; if `LANGFUSE_PUBLIC_KEY` is set, also forwards the event to Langfuse Cloud (wrapped in try/except so a Langfuse outage never breaks the app). Must work with zero Langfuse configuration — the Postgres write is the source of truth.

### Implement minimally (just enough for the vertical slice)

`schema_tools.py` (`list_schema` returns table/column names from `schema.sql` metadata — parse it once at startup, don't hardcode); `validate_tool.py` and `chart_tool.py` as thin wrappers; `clarify_tool.py` returning a structured `NeedsClarification(question: str)` that the graph treats as a terminal state; `agent/prompts.py` (one system prompt embedding the schema block, glossary, and explicit tool-use instructions — no chain-of-thought scaffolding, just a clear description of each tool and when to use it); FastAPI `POST /ask {question} → {sql, status: executed|blocked|needs_clarification|error, rows, answer, chart_spec?, tool_calls: [...], trace_id}` and `GET /health`; Streamlit page with a question box, an expandable "agent trace" panel showing each tool call in order (reading from `agent_traces` for past runs), result table, chart, and a red "Blocked by SQL safety policy" banner path; `deploy/provision.sh` as a documented, idempotent bash script (apt install postgresql-16, postgresql-16-pgvector, caddy; download and install the cloudflared .deb; create the `t2sql_ro` role; enable the two systemd units) — this session writes and documents the script but does NOT execute it against any real server.

### Stub only

`retrieval/*`, `glossary_tools.py` (reads `glossary.yaml` but returns a fixed lookup, no fuzzy matching yet), `retrieval_tools.py` (`search_examples` stub — pgvector wiring only), Vietnamese time-expression resolution, and both `eval/datasets/external/download_*.py` scripts (print the dataset license notice, download into git-ignored `data/external/`, and do NOT run them in this session).

### Seed content you must author

- `eval/datasets/core_vi/questions.jsonl` — 5 REAL items against the schema; execute and verify each `gold_sql` before committing (against the schema, e.g. with a throwaway local sqlite/postgres you control, or by hand — never guess). One JSON object per line, exactly this shape:
  `{"id":"q001","question_vi":"Top 5 khách hàng có doanh thu cao nhất tháng 6/2026?","question_en":"Top 5 customers by revenue in June 2026","gold_sql":"SELECT ...","tags":["join","aggregate","time_range"],"difficulty":"medium","notes":""}`
- `eval/datasets/security/attacks.jsonl` — 10 cases with `"expected_behavior":"blocked"` covering: DROP; multi-statement `; DELETE`; UPDATE; `pg_catalog` probe; sensitive-column SELECT; UNION-based exfiltration; comment smuggling; missing LIMIT (expected: rewritten, not blocked); unbounded cartesian join; injection phrased inside a natural-language question.
- `db/glossary.yaml` — 3 completed Vietnamese term mappings (`doanh thu`, `miền Nam`, `quý trước`) plus 15 TODO keys.
- `eval/configs/baseline.yaml` and `eval/configs/ablations/*.yaml` placeholders — each ablation file changes exactly ONE factor relative to baseline and names it in a header comment.
- `deploy/Caddyfile` — one reverse-proxy block for the API, one for the Streamlit UI, both behind the same domain via path or subdomain (your choice; document it).
- `deploy/systemd/*.service` — standard `[Unit]/[Service]/[Install]` units running the venv's `uvicorn`/`streamlit` binary, `Restart=on-failure`, running as a non-root service user.

## Makefile targets (all must work; none require Docker)

`make venv` (create/sync the virtualenv) · `make seed` (runs `db/seed.py` against `DATABASE_URL` — works against a local SSH-tunneled dev DB or does nothing gracefully if unset) · `make demo-offline` (runs the agent loop on the 5 seed questions with `OFFLINE_MODE=1`, prints each tool call in order plus the final answer + chart spec — must visibly show at least one retry-after-failure sequence, no database, no network) · `make smoke` (offline eval on the 5 items → `eval/results/<run_id>/summary.md` with strict/relaxed EX plus average tool calls per question) · `make test` · `make lint` · `make run-api` (`uvicorn` directly) · `make run-ui` (`streamlit run` directly) · `make eval CONFIG=eval/configs/baseline.yaml` (for later online runs; offline it must fail gracefully with a clear message).

## Tests (pytest; all runnable offline, no Docker, no network, no live database required)

- `tests/test_ast_policy.py` — ≥15 red-team cases mirroring `attacks.jsonl`, plus ≥3 legitimate SELECTs that must pass.
- `tests/test_scoring.py` — strict vs relaxed disagreement cases: row order, extra column, NULL vs "NULL", float rounding, and an ORDER-BY-required case.
- `tests/test_readonly_role.py` — an INSERT through the app connection must fail at the DATABASE level. Skip with a clear message (e.g. "no DATABASE_URL configured — run against a provisioned Postgres to exercise this test") when no database is reachable; never silently pass.
- `tests/test_agent_offline.py` — full agent loop run on one fixture question that requires at least 2 tool calls (e.g. a failed `execute_sql` followed by a corrected retry).
- `tests/test_execute_tool_bypass.py` — **must exist**: call `execute_sql` directly with a disallowed statement WITHOUT calling `validate_sql` first, and assert it is still blocked. This is the test that proves the "agent can't opt out of policy" claim is real, not documentation.
- `tests/test_max_iterations.py` — a fixture sequence that always fails must terminate at exactly `max_iterations` with a structured "could not complete safely" result, not an exception or an infinite loop.

## Done when (run every item yourself; print ✅/❌ per line before finishing)

1. `make venv` completes with no errors, using only `pip`/`uv` — confirm no Docker command appears anywhere in the repo (`grep -ri docker .` returns nothing except this sentence in docs, if you choose to note the constraint there).
2. `make demo-offline` prints, for each of the 5 questions, the ordered tool-call trace and the final answer, with at least one visible retry, and zero API keys, zero database, zero network.
3. `make test` green (including `test_execute_tool_bypass.py` and `test_max_iterations.py`; `test_readonly_role.py` may legitimately skip with a clear message if no database is configured); `make lint` clean.
4. `make smoke` writes `summary.md` containing strict/relaxed EX and average tool calls per question for the 5 items.
5. Bypass proof: `test_execute_tool_bypass.py` passes — policy is enforced even when the agent skips explicit validation.
6. `deploy/provision.sh`, `deploy/Caddyfile`, and the two systemd unit files exist, are internally consistent (same service names, same ports, same paths), and are documented in the README — but were NOT executed against any real server this session.
7. `git status` shows no data files, no secrets, no raw results, no tunnel tokens; the README quickstart commands are the exact commands you ran.
8. `docs/DECISIONS.md` lists every choice you made that this spec did not specify, including anywhere you were tempted to reach for a container and didn't.

## Out of scope this session

Real retrieval implementation, Vietnamese time-expression resolver, authentication, React UI, actually provisioning a VPS or running `deploy/provision.sh` against a real server, actually setting up a Cloudflare Tunnel, downloading any external dataset, running any benchmark, anything involving Docker or Kubernetes in any form.
