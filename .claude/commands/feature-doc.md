---
description: Scaffold the plan and change document for a feature (docs/plan + docs/features)
argument-hint: <feature-name> [short description]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Scaffold the feature documentation for: **$ARGUMENTS**

Follow [.claude/skills/feature-docs/SKILL.md](../skills/feature-docs/SKILL.md).

1. Derive a kebab-case `<feature-slug>` from the feature name and confirm it with the user
   if it is ambiguous.
2. Read the parts of `src/` the feature touches so the documents describe the real code.
3. Create `docs/plan/<today>-<feature-slug>.md` from
   [templates/plan.md](../skills/feature-docs/templates/plan.md) — use the actual current
   date from `date +%F`.
4. Create `docs/features/<feature-slug>.md` from
   [templates/change.md](../skills/feature-docs/templates/change.md), leaving the
   post-implementation sections marked `TBD` until the code is written.
5. Fill in everything you can already answer — especially **why we need this change**.
   Leave a clearly marked `TBD` where you genuinely need input from the user, and list
   those gaps at the end of your reply.
6. Add a link to the new feature doc in [docs/README.md](../../docs/README.md).

Do not implement the feature in this command — plan and document only.
