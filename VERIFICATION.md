# Verification evidence

## Executed checks

- 33/33 automated tests passed with `python -m unittest discover -s tests -v`.
- Native Hermes `plugins doctor . --ci` passed runtime discovery, manifest import and registration.
- `plugins validate . --json` returned ok:true. Scanner warning remains on original vendored debugging example and exact transformation/signature strings. These are retained source/patch evidence; no startup execution of that example. Generated runtime skills independently scan safe.
- Real Hermes PluginManager in fresh temporary HERMES_HOME registered 43 namespaced skills: 42 upstream + one local guide. Every qualified path exists. This is real runtime loading, not a mock-context-only assertion.
- Bundle validator: 42/42 expected skills; no findings. All11 critical adapter signatures passed.
- 153 vendored skill files compared byte-for-byte with pinned reviewed source checkouts: no mismatch. Upstream license files separately retained.
- Real Hermes skills_guard: all42 generated skill directories safe.
- Public upstream check executed: Matt4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d and Superpowers8ca22dba9a94f28898bbce59f2537ff4d87c747d current; no inventory changes.
- Real current upstream content staged/scanned42 skills; applied twice into disposable state; status verified true; rollback to verified previous generation succeeded. No working-profile generation was changed by this test.
- Local Git fixture tests cover source inventory additions, acceptance gates, changed anchors, symlinks, concurrency, corrupt state/receipts, scanner caution/danger blocking and rollback.
- Disposable calculator tests failed RED for NotImplementedError, then passed GREEN (2 tests). This proves real test execution; it is NOT a model-driven workflow evaluation.

## Limits

Model-driven brainstorming/grilling/build dialogue has not yet been evaluated end-to-end here. Runtime reminder selection and namespace loading are tested; this cannot guarantee a model's judgment or compliance. Compaction persistence remains explicit opt-in recovery, not a sticky mode. Existing chats do not auto-reregister changed skill pointers; use a fresh session after activation/update. No upstream optional servers, telemetry service, transcript exports, user coding project setup or connected tracker writes executed.

Active-profile installation and private GitHub publication verification will be recorded after those steps finish. No result is claimed before read-back.
