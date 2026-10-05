# Freyja Engineering skill adapter

Adapter version 1 builds the pinned Matt Pocock and Superpowers inventories into a Hermes plugin bundle. The generated runtime folders live directly at `skills/matt-<slug>/` and `skills/sp-<slug>/` (42 directories total). This source layout is intentionally flat so native skill discovery and `BundleManager.status()` bundled fallback use the same path.

`build_bundle(vendor_root: Path, output_root: Path, lock: Mapping, *, signature_policy: Optional[Mapping] = None) -> dict` generates a complete generation beneath `output_root`: `output_root/skills/` contains generated folders, `output_root/vendor/{source}/LICENSE` preserves licenses, and `output_root/build.json` records the receipt. The caller may then publish the generated `skills/` contents as a flat runtime root. `output_root` must be absent or empty; builds stage transactionally and replace it only after validation succeeds. Inputs are pinned by `upstream.lock.json`; symlinked/unsafe vendor trees and signature drift are rejected.

The optional `signature_policy` keyword exists solely for reduced synthetic test fixtures; it explicitly supplies their expected checked anchors. Production calls omit it and always load the checked-in versioned signature manifest, including all security anchors. Do not pass fixture policy from the updater or production build flows. `validate_adapter_signatures(vendor_root, lock)` reports `ok`, `checked_signatures`, and findings. `validate_bundle(output_root, lock)` accepts either a generation root containing `skills/` or the direct flat runtime skills root and returns `ok`, `skill_count`, `expected_skill_count`, and findings.

Adapter transformations rename frontmatter and sibling skill invocations into the `freyja-engineering:<slug>` namespace, preserve sidecars and local references, append compatibility/authorization guidance, and adapt reviewed defaults for HTML output/CDN use, secret output, environment-value printing, and worktree cleanup. Signature preconditions fail closed when an upstream anchor changes. Upstream originals remain untouched under `vendor/`.

## Verification

Run `python3 -m unittest discover -s tests -v` from the repository root. The real Hermes scanner requires Python 3.10+; run it with a compatible interpreter and the Hermes installation root on `PYTHONPATH`. The adapter API itself remains compatible with Python 3.9.
