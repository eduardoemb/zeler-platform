# Skill Registry — zeler-platform

**Delegator use only.** Any agent that launches sub-agents reads this registry to resolve compact rules, then injects them directly into sub-agent prompts. Sub-agents do NOT read this registry or individual SKILL.md files.

> **Note**: The canonical skill registry for this project is maintained in this
> repository at `/Users/eduardoramirez/Documents/repositorios/zeler-platform/.atl/skill-registry.md`
> per `AGENTS.md`.

## User Skills

| Trigger | Skill | Path |
|---------|-------|------|
| Atlas Stream Processing workspaces, connections, processors, diagnostics, or tier sizing | atlas-stream-processing | /Users/eduardoramirez/.config/opencode/skills/atlas-stream-processing/SKILL.md |
| Creating a pull request, opening a PR, or preparing changes for review | branch-pr | /Users/eduardoramirez/.config/opencode/skills/branch-pr/SKILL.md |
| User mentions ctx7/context7, needs current docs, skill management, or Context7 MCP setup | context7-cli | /Users/eduardoramirez/.agents/skills/context7-cli/SKILL.md |
| Building or beautifying frontend UI, pages, dashboards, components, or layouts | frontend-design | /Users/eduardoramirez/.agents/skills/frontend-design/SKILL.md |
| Writing Go tests, Bubbletea TUI tests, teatest, or improving Go test coverage | go-testing | /Users/eduardoramirez/.config/opencode/skills/go-testing/SKILL.md |
| Creating a GitHub issue, reporting a bug, or requesting a feature | issue-creation | /Users/eduardoramirez/.config/opencode/skills/issue-creation/SKILL.md |
| Explicit adversarial / dual review requests such as judgment day, doble review, or juzgar | judgment-day | /Users/eduardoramirez/.config/opencode/skills/judgment-day/SKILL.md |
| MongoDB client connection pooling, timeouts, lifecycle, or connection error handling | mongodb-connection | /Users/eduardoramirez/.config/opencode/skills/mongodb-connection/SKILL.md |
| MongoDB MCP environment setup, Atlas auth, or local Atlas configuration | mongodb-mcp-setup | /Users/eduardoramirez/.config/opencode/skills/mongodb-mcp-setup/SKILL.md |
| Generating read-only MongoDB find/aggregate queries from natural language | mongodb-natural-language-querying | /Users/eduardoramirez/.config/opencode/skills/mongodb-natural-language-querying/SKILL.md |
| Query performance, explain plans, indexing, or slow-query optimization | mongodb-query-optimizer | /Users/eduardoramirez/.config/opencode/skills/mongodb-query-optimizer/SKILL.md |
| MongoDB data modeling, embed vs reference, migrations, validation, or schema review | mongodb-schema-design | /Users/eduardoramirez/.config/opencode/skills/mongodb-schema-design/SKILL.md |
| Atlas Search, Vector Search, hybrid search, substring search, or multi-field search use cases | mongodb-search-and-ai | /Users/eduardoramirez/.config/opencode/skills/mongodb-search-and-ai/SKILL.md |
| Creating new AI skills, agent instructions, or reusable AI workflows | skill-creator | /Users/eduardoramirez/.config/opencode/skills/skill-creator/SKILL.md |

## Compact Rules

### atlas-stream-processing
- Use Atlas stream tools only for ASP, not general MongoDB queries or Atlas cluster admin.
- All operations require `projectId`; inspect/list before mutate/delete.
- Before composing any processor pipeline, query MongoDB knowledge/docs first to validate stage fields.
- Processor pipelines must start with `$source` and end with `$merge`, `$emit`, `$https`, or async `$externalFunction`.
- Never use invalid streaming constructs like `$$NOW`, sinkless deployed pipelines, or HTTPS as `$source`.
- Stop processors before modifying; deleting a workspace requires explicit user confirmation after inspection.

### branch-pr
- Every PR MUST link an approved issue and include exactly one `type:*` label.
- Branch names must match `type/description` with lowercase `a-z0-9._-` only.
- Use conventional commits only; never add `Co-Authored-By` trailers.
- Run shellcheck on modified scripts before opening the PR.
- PR body must include linked issue, one PR type, summary bullets, changes table, and test plan.
- Blank PRs or PRs without issue linkage are blocked by automation.

### context7-cli
- Keep ctx7 current with `npm install -g ctx7@latest` or use `npx ctx7@latest`.
- Resolve docs in two steps: `ctx7 library <name> <query>` then `ctx7 docs <libraryId> <query>`.
- Library IDs must include the leading `/`.
- Use `ctx7 skills *` commands for install/search/list/remove/generate workflows.
- `skills generate` requires login; `ctx7 setup` also needs login unless API key or oauth is provided.

### frontend-design
- Choose a bold, explicit aesthetic direction before coding; be intentional, not generic.
- Avoid default AI-looking choices like Inter/Arial, bland layouts, and cliché purple gradients.
- Make typography, color, motion, and composition carry the visual identity.
- Match implementation complexity to the aesthetic: restraint for minimalism, richer code for maximalism.
- Ship real working UI code, not static mockups or decorative fluff.

### go-testing
- Default to table-driven tests for functions with multiple scenarios.
- Test Bubbletea state transitions through `Model.Update()` directly.
- Use `teatest.NewTestModel()` for interactive full-flow TUI tests.
- Use golden files for visual output snapshots.
- Mock side effects, use `t.TempDir()` for filesystem work, and skip real command integration under `--short`.

### issue-creation
- Always search for duplicates before creating a new issue.
- Use the repo issue templates; blank issues are disabled.
- New issues get `status:needs-review`; PRs must wait for `status:approved`.
- Questions belong in Discussions, not Issues.
- Bug reports need repro steps and expected/actual behavior; feature requests need problem, solution, and affected area.

### judgment-day
- Only run when the user explicitly asks for judgment day / dual review.
- Resolve project skills first, then inject the same project-standards block into both judges and the fix agent.
- Launch exactly two blind judges in parallel; the orchestrator never reviews directly.
- Only confirmed CRITICALs and real WARNINGs block approval; theoretical warnings become INFO.
- After Round 1, ask the user before fixing confirmed issues; re-judge after fixes.

### mongodb-connection
- Never suggest pool or timeout values without first understanding workload and deployment context.
- Reuse a single MongoClient; in serverless, initialize it outside the handler.
- Account for monitoring connections when sizing total cluster connections.
- Prefer default pool sizes unless concurrency, latency, or burst data justifies overrides.
- Distinguish infrastructure problems from client-config problems before recommending changes.

### mongodb-mcp-setup
- Never ask for, store, or handle credentials directly; instruct the user to add them locally.
- Check existing `MDB_MCP_*` variables first and detect partial configuration.
- Offer the three setup paths: connection string, Atlas service account, or Atlas Local.
- For Atlas service accounts, remind the user the client secret is shown once and API access list entry is mandatory.
- Prefer storing exports in a dedicated `~/.mcp-env` file sourced by the shell profile.

### mongodb-natural-language-querying
- Gather indexes, schema, and sample docs before generating the query.
- Validate every field against the schema; MongoDB silently ignores unknown fields.
- Prefer `find` over aggregation unless grouping, joins, or multi-stage transforms are required.
- Return the query in JSON with stringified MongoDB syntax, not raw objects.
- Never use write pipelines; this skill is read-only.

### mongodb-query-optimizer
- Use this only for performance/indexing help, not routine query authoring.
- For a concrete query, inspect indexes, run `explain`, and sample documents before recommending changes.
- Prefer high-impact compound indexes that match the query shape and ESR ordering.
- Use Atlas Performance Advisor when available; do not invent drop-index recommendations without it.
- Never create indexes automatically unless the user explicitly approves.

### mongodb-schema-design
- Design from access patterns: data accessed together should be stored together.
- Favor embedding for 1:1 and bounded 1:few relationships; reference when data is independent or unbounded.
- Do not recreate SQL normalization blindly in MongoDB.
- Use schema validation and schema versioning to control drift during evolution.
- Watch for anti-patterns like unbounded arrays, excessive lookups, unnecessary collections, and unused indexes.

### mongodb-search-and-ai
- Inspect schema, indexes, and cluster version before recommending search solutions.
- Choose lexical, vector, or hybrid search based on the actual user need.
- Never recommend `$regex` or `$text` for real search workloads; use Atlas Search instead.
- Explain index definitions first and require explicit approval before creating them.
- If only read-only tools are available, provide the exact index JSON and query pipeline for the user to apply.

### skill-creator
- Create a skill only for reusable patterns or project-specific AI guidance, not one-off tasks.
- Use the standard `skills/{skill-name}/SKILL.md` layout with optional `assets/` and `references/`.
- Frontmatter must include name, description with Trigger, Apache-2.0 license, author, and version.
- Keep examples minimal, focus on critical patterns, and avoid duplicating existing docs.
- Register the new skill in `AGENTS.md` after creation.

## Project Conventions

| File | Path | Notes |
|------|------|-------|
| AGENTS.md | /Users/eduardoramirez/Documents/repositorios/zeler-platform/AGENTS.md | Project rules: strict TDD, conventional commits, no AI attribution, never commit without being asked, do not mutate `../zeler-core` unless explicitly requested. Stack: Python 3.11 + uv workspace + FastAPI + MongoDB + RabbitMQ/CloudAMQP + GCP. SDD design at `sdd/zeler-platform-greenfield/design.md`. |

## SDD Local References

| Artifact | Path |
|----------|------|
| SDD Home | `/Users/eduardoramirez/Documents/repositorios/zeler-platform/sdd/zeler-platform-greenfield/` |
| Canonical Skill Registry | `/Users/eduardoramirez/Documents/repositorios/zeler-platform/.atl/skill-registry.md` |
| Legacy Context Only | `zeler-core` references may appear in migration/decommission docs, but they are not canonical for active platform work. |
