# Updating Freyja Engineering skills

Updates are manual. Plugin startup and ordinary skill loading never access the network.

From this plugin checkout:

```sh
python -m freyja_engineering status
python -m freyja_engineering check
python -m freyja_engineering update                 # verify and stage only
python -m freyja_engineering update --apply         # atomically activate verified bundle
python -m freyja_engineering rollback               # restore previous verified generation
```

The checker reads `main` from the two fixed HTTPS GitHub repositories and compares their revisions and promoted inventory with `upstream.lock.json` and `plugin.yaml`. It does not execute upstream scripts. The updater downloads a pinned commit, verifies its SHA, rejects links/special paths, calls the bundle adapter and validator (including its critical-anchor preconditions), and scans all generated skills with the installed Hermes `tools.skills_guard` scanner. Missing scanner, scan errors, any non-safe verdict, adapter conflicts, or inventory drift fail closed. `--accept-inventory-changes` is required to apply a changed inventory; it is an explicit approval, not a bypass of validation or scanning.

Without `--apply`, a successful update creates a verified candidate under the runtime state directory and leaves active skills unchanged. `--apply` builds and verifies a full new generation outside this tracked plugin tree, records a SHA-256 receipt, and atomically switches `state.json`; the bundled plugin sources remain intact. Runtime state defaults to `$HERMES_HOME/plugin-data/freyja-engineering` (or `~/.hermes/plugin-data/freyja-engineering`). Use `--state-root PATH` only for an explicit alternate location. `status` reports the selected skills root and lock; a missing/corrupt pointer falls back to bundled skills without mutating state. Rollback verifies both the state pointer and previous generation receipt before switching.

`check()` returns `current`, `update_available`, `upstream_revision` (source-to-commit map), and `sources` (each source’s locked/upstream SHA and inventories). `update(apply=False, accept_inventory_changes=False)` returns a `staged` result with `candidate_root`, or an `applied` result with `generation` and `active_root`; both carry `verified` and `receipt`. `rollback()` returns `rolled_back`, generation and active root. `status()` returns `active_root`/`root`, selected `lock`, `source` (`generation` or `bundled`), `generation`, and `verified`.

This changes only this plugin's bundled Matt/Superpowers content. It does not install, replace, or remove profile-level skills. Check/update require Git and network access; tests may inject local Git fixtures/scanners through the Python API, but the public CLI accepts no arbitrary repository URLs.
