# <Feature name>

- **Slug:** `<feature-slug>`
- **Status:** shipped | partial | reverted
- **Plan:** [../plan/YYYY-MM-DD-<feature-slug>.md](../plan/YYYY-MM-DD-<feature-slug>.md)

## Summary

Two or three sentences: what this feature does, from the user's point of view.

## Why we need this change

The problem that existed before this change, who it affected, and what it cost to leave
it alone. Include the trigger (ticket, incident, requirement) and the constraints that
shaped the solution. Do not describe the solution here — only the need.

## What changed

| Area | Change |
| --- | --- |
| Modules | `src/...` — added / modified |
| Endpoints | `METHOD /path` — added / modified / removed |
| Data | tables, entities, migrations |
| Config | new env vars and their defaults |
| Dependencies | packages added or removed |

## How it works

The flow end to end: entry point, services involved, external calls, and what is
returned or persisted. Link to the source files rather than pasting large blocks.

### Key decisions

- **Decision** — why, and what was rejected instead.

## Impact

- **Breaking changes:** none | describe them and the migration path.
- **Migrations / setup:** commands to run, env vars to set before deploy.
- **Performance & cost:** extra latency, external API usage, quotas.
- **Security & privacy:** data handled, who can access it, what is logged.

## How to verify

1. Steps to exercise the feature locally.
2. Automated tests that cover it: `npm test -- <pattern>`.

## Follow-ups

- Known gaps and deferred work.

## Change log

| Date | Change | Author |
| --- | --- | --- |
| YYYY-MM-DD | Initial implementation | |
