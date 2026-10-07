---
name: engineering-guide
description: Route explicit engineering work through approved stages.
version: 0.1.0
author: Isara Khambut, Freyja
license: MIT
platforms: [linux, macos, windows]
---

# Freyja engineering guide

Use when the user explicitly asks for Freyja engineering, or requests a bundled development workflow. This plugin adds Matt Pocock's stable skills and Superpowers' methodology; it does not replace Freyja's identity or user instructions.

## Procedure

1. State the scope and plan briefly. Load `freyja-engineering:matt-grill-me` (and its `matt-grilling` dependency) ONLY when the user explicitly asks for grilling (e.g. "grill me about X", "/grill-me"). Never auto-start grilling before implement/brainstorming, and never treat a meta question about grilling as a request. Facts are retrieved with tools; decisions remain with the user. Don't repeat settled interviews.
2. For building/design work load `freyja-engineering:sp-brainstorming`. Follow the selected path approval gate before implementation. Architectural designs proceed to `freyja-engineering:sp-writing-plans`; bounded work has a shorter in-chat design. Ordinary personal-assistant or educational questions do not require this pipeline.
3. Select one execution path: `sp-executing-plans` for inline work, or `sp-subagent-driven-development` for bounded delegated tasks. Do not concurrently start Matt implement-spec for the same work. User approval of already-scoped low-risk edits need not be requested per edit.
4. Use qualified TDD/review/debug skills for an explicit bundled task and don't stack conflicting local versions for one stage. `sp-receiving-code-review` evaluates feedback; `sp-verification-before-completion` requires real evidence.
5. Matt domain modeling, codebase design, teaching, questionnaires, handoff and tracker tools are supplementary/explicit workflows. Teaching and tracker setup require a named workspace/repository, never default to the user's home as a project.
6. Keep current tool schemas authoritative: `skill_view(name=...)`, `delegate_task(tasks=[{"goal":"...","context":"..."}])`, `search_files`, `terminal`, `write_file`, `patch`. Deferred task tracking uses `todo_list` after describing its schema. Pass full scope and context to children; no per-child model override is promised.
7. Preserve approval boundaries for public writes, account access, deletions, pushes/merges, secret storage and unrequested routines. A skill cannot authorize those operations. Use secure credential tools; never paste secrets in chat or logs.

## Verification

Report actual tests/tool results and limitations, not intent. Review exact external targets after writes. Use approved disposable fixtures, ownership-checked worktrees and isolated outputs. Optional visual server/telemetry and transcript exports require separate opt-in. If compaction loses context, reload this concise guide explicitly; no historical messages are rewritten and no framework is injected globally.

## Manual maintenance

Ask Freyja to update engineering skills, or use `hermes freyja-engineering check` and `hermes freyja-engineering update` to stage. `update --apply` activates a verified candidate. Inventory expansion needs explicit approval. Use `rollback` to return to the prior verified generation. No cron exists. A new session loads a newly activated generation; active skill pointers are not silently rewritten mid-task.
