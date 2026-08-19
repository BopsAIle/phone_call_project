---
name: feature-docs
description: Plan-then-document workflow for new features in this repo. Use whenever a feature, endpoint, module, integration, or behaviour change is requested — write the plan to docs/plan/ before coding, and the change document to docs/features/ after coding, explaining why the change was needed.
---

# Feature documentation workflow

Every feature in this repository produces two documents. Do not treat them as
optional cleanup: the plan gates the code, and the change doc closes it out.

| Stage | File | When |
| --- | --- | --- |
| Plan | `docs/plan/YYYY-MM-DD-<feature-slug>.md` | Before writing any code |
| Change doc | `docs/features/<feature-slug>.md` | After the code works |

`<feature-slug>` is kebab-case and stable across both files (e.g. `call-transcription`,
`google-calendar-sync`). Use today's real date for the plan file.

## Step 1 — Plan (before coding)

1. Restate the request in your own words and confirm the scope.
2. Read the code the feature touches so the plan reflects reality, not guesses.
3. Copy [templates/plan.md](templates/plan.md) to `docs/plan/YYYY-MM-DD-<feature-slug>.md`
   and fill in every section. Delete a section only if it genuinely does not apply,
   and say so rather than leaving placeholder text.
4. Show the plan to the user before implementing anything non-trivial.

The plan is a living file: as the implementation deviates, update the plan and note
what changed and why, so the two documents never contradict each other.

## Step 2 — Implement

Follow the plan. If you discover the plan is wrong, update it first, then continue.

## Step 3 — Change document (after coding)

1. Copy [templates/change.md](templates/change.md) to `docs/features/<feature-slug>.md`.
   If the file already exists, append a new entry to its Change log instead of
   overwriting the history.
2. **Why we need this change** is the most important section. Write the problem, not
   the solution: what was broken or missing, who it affected, and what it cost to leave
   it alone. "The user asked for it" is never a sufficient answer.
3. Fill in what changed, how it works, and the impact (breaking changes, migrations,
   new env vars, rollout and rollback).
4. Link the doc from `docs/README.md`.
5. Link back to the plan file, and from the plan to the change doc.

## Sizing the document

Match the depth to the change. A new endpoint might need half a page; a new integration
with an external provider needs the full template. Never skip the "why" section
regardless of size.

## Quality bar

- Concrete over vague: name the modules, endpoints, tables, and env vars.
- Record decisions **and** the alternatives that were rejected, with the reason.
- Keep code snippets short — link to the source file instead of pasting it.
- No secrets, API keys, tokens, or real customer data in any doc.
- Use relative Markdown links, e.g. `[app.module.ts](../../src/app.module.ts)`.
