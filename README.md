# Freyja Engineering

A native Hermes plugin combining the **27 promoted Matt Pocock skills** and **15 Superpowers skills**, with explicit namespacing, Hermes compatibility adaptations and manual upstream maintenance. Built for Freyja, Isara's personal AI assistant. No cron, automatic updates, telemetry service or transcript mining runs at startup.

## What is installed

- `freyja-engineering:matt-<skill>`: Matt Pocock's stable set; misc/beta excluded.
- `freyja-engineering:sp-<skill>`: Superpowers skills, without its independent global bootstrap.
- `freyja-engineering:engineering-guide`: local routing and consent policy (one additional guide).

42 upstream skills plus one local guide. Existing Hermes skills remain untouched. Full inventory/revisions live in `upstream.lock.json`.

## Use

Say **"Use Freyja engineering to build …"** to request the workflow. Say **"grill me about …"** for Matt's decision interview without automatically starting coding. `/engineering-mode` shows opt-in guidance; it does not execute code by itself.

Explicit skill loading works through Hermes `skill_view(name="freyja-engineering:matt-grill-me")` or `skill_view(name="freyja-engineering:sp-brainstorming")`. Plugin skills are namespaced; do not assume every desktop/chat surface exposes the same skill slash shortcuts. Natural-language explicit requests or qualified loader calls are portable.

Normal finance, planning and personal-assistant messages do not receive mandatory engineering bootstrap instructions. Opt-in routing is intentionally explicit, not a guarantee of autonomous workflow detection. A small context hint is injected for explicit trigger messages, including later turns, instead of rewriting historical messages or injecting a framework every turn. After compaction, repeat the opt-in or load the guide; no guaranteed persistent mode is claimed.

## Workflow

1. Optional Matt grilling for uncertain ideas or decisions.
2. Superpowers brainstorming for an approved design; reuse settled answers.
3. Architectural tasks proceed to writing-plans; bounded tasks use shorter design gates.
4. Pick one execution path, then real tests/review/verification.
5. Matt domain-modeling, teaching, questionnaires and tracker tools are supplemental.

Skill instructions are not authorization for private account reads, public writes, destructive cleanup, pushes/merges, credential storage or schedules. Optional visual companion and diagnostic exports are separate opt-ins. Use owner-checked workspaces and no raw secrets in logs.

## Install

The plugin needs a supported Hermes runtime and Git; it has no extra Python package dependencies.

For a Git-backed installation after publication:

```bash
hermes plugins install isara-kh/freyja-engineering --no-enable
hermes plugins enable freyja-engineering
```

The repository is private: GitHub credentials must be available to the native Hermes installer. Do not put tokens in URLs or files. Restart/open a fresh Hermes session after activation. Installation should follow validation rather than blindly enabling downloaded Python.

## Manual upstream updates

```bash
hermes freyja-engineering status
hermes freyja-engineering check
hermes freyja-engineering update
hermes freyja-engineering update --apply
hermes freyja-engineering rollback
```

`check` reads the two fixed public upstream repositories. `update` stages by default. `--apply` activates a candidate only after adaptation, validation and real Hermes static scans. Inventory additions/removals require the explicit `--accept-inventory-changes` flag and review. An adaptation conflict or unavailable scanner fails closed. Open a new session to register a newly active generation; existing sessions keep their prior paths.

`hermes plugins update freyja-engineering` updates **this wrapper's code** from its Git origin, not the two upstream dependency revisions by itself. Local manually copied installs need Git provenance adoption or a later native install before that code-update command can work. `python -m freyja_engineering` provides the same source-maintenance CLI when run from a checkout; see `UPDATING.md`.

Runtime generations/receipts live outside the Git working tree under the active profile's plugin-data directory. Upstream originals, source locks and compatibility code are tracked separately. Do not hand-edit generated skill copies; change/test the adapter and rebuild.

## Development

```bash
python -m unittest discover -s tests -v
hermes plugins doctor . --ci
hermes plugins validate . --json
```

Tests use local synthetic/Git fixtures and actual artifact checks, not user transcripts or tracker changes. Scanner availability is required for real candidate activation. See `SPEC.md`, `TASKS.md` and `ADAPTER.md` for implementation details and scope. Real runtime and behavior evidence is recorded in `VERIFICATION.md` once completed; unit tests are not claims of deterministic model compliance.

## Sources and attribution

- [Matt Pocock skills](https://github.com/mattpocock/skills), MIT.
- [Superpowers](https://github.com/obra/superpowers), Jesse Vincent/Prime Radiant, MIT.

Original source files and license notices are preserved in `vendor/`. This project is an independent adaptation, not an upstream-endorsed distribution. No pstack content is bundled.
