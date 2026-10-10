# PNGtuber Studio

Local Windows app that turns a recorded 9-ball pool rack into a finished PNGtuber video: cut footage, write and generate cloned-voice lines, direct an avatar on a timeline, export a 1080p video plus every individual asset. Runs fully offline after the first-run model download.

**Status:** design complete, scaffolded, implementation not started. See `PROJECT_STATE.md`.

## Docs

| File | Purpose |
|---|---|
| `CLAUDE.md` | Instructions and business rules for AI assistants |
| `PROJECT_STATE.md` | Living snapshot: what exists, where it lives, how to run |
| `IMPLEMENTATION_PLAN.md` | Milestones M0 to M7 and task checklist |
| `docs/DESIGN_SPEC.md` | Full design spec |
| `docs/tasks/` | Per-task breakdowns (`_TEMPLATE.md`, `M0-spike.md`) |

## Working with an AI assistant

No agent tooling: everything is done in a plain chat by hand. Start each task in a fresh chat with `CLAUDE.md`, `PROJECT_STATE.md`, the task file, and any source files the task names. The assistant writes code and commands; you run them on Windows and paste results back. Details and a suggested first message are in `IMPLEMENTATION_PLAN.md`.
