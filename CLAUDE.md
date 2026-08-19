# CLAUDE.md

Project instructions for `ai_receptionist_backend` (NestJS + TypeScript).

## Commands

- Dev server: `npm run start:dev`
- Build: `npm run build`
- Lint: `npm run lint`
- Format: `npm run format`
- Tests: `npm test` / `npm run test:e2e`

## MANDATORY: document every new feature

Any change that adds or meaningfully alters a feature MUST ship with documentation.
This is not optional and is not a follow-up task — the feature is not done until both
files exist.

1. **Before writing code** — create the plan file:
   `docs/plan/YYYY-MM-DD-<feature-slug>.md`
   Template: [.claude/skills/feature-docs/templates/plan.md](.claude/skills/feature-docs/templates/plan.md)

2. **After the code is written** — create/update the change document:
   `docs/features/<feature-slug>.md`
   Template: [.claude/skills/feature-docs/templates/change.md](.claude/skills/feature-docs/templates/change.md)

   It must always answer, at minimum:
   - **Why we need this change** — the problem, who is affected, cost of doing nothing.
   - **What changed** — modules, endpoints, DB/schema, config, dependencies.
   - **How it works** — flow of the feature, key decisions and trade-offs.
   - **Impact** — breaking changes, migrations, env vars, rollout/rollback.

3. Link the new doc from [docs/README.md](docs/README.md).

The full workflow lives in [.claude/skills/feature-docs/SKILL.md](.claude/skills/feature-docs/SKILL.md);
follow it whenever a feature is requested. `/feature-doc <feature-name>` scaffolds both files.

### Scope

- Applies to: new endpoints, modules, integrations, background jobs, schema changes,
  auth/permission changes, and any change to externally visible behaviour.
- Does not apply to: typo fixes, formatting, dependency bumps with no behaviour change,
  and pure internal refactors that change no behaviour (mention those in the PR instead).

## Conventions

- Branch names: `feat/<short-name>` for features, `fixBug/<short-name>` for bug fixes.
  Create the branch before starting work.
- Run `npm run lint` and `npm run build` before committing.
- Never commit `.env` files or secrets. Never use `--no-verify`.
- Docs are written in English, in Markdown, and use relative links.
