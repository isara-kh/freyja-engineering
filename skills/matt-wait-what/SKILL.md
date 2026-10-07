---
name: matt-wait-what
description: "Stop. That last message did not land: re-pitch it."
disable-model-invocation: true
---

## Freyja / Hermes compatibility

This is the `matt`-namespaced adaptation of the upstream `matt-wait-what` skill. Use Hermes-native tools and syntax; invoke sibling skills by their fully qualified `freyja-engineering:<skill-slug>` name. Do not assume a generic `Skill` tool exists. Interview and grilling skills (`matt-grill-me`, `matt-grilling`, `matt-grill-with-docs`) are explicit opt-in only: never auto-load them before implement or brainstorming, and never treat a meta question about grilling as a request. Honor current user authorization and do not expose secrets in logs, output, or artifacts.

Wait, I don't understand where you've got to here. Re-pitch that: give me a little bit of context, talk in ASD-STE100 Simplified Technical English, and use the ubiquitous language from `GLOSSARY.md` (follow `GLOSSARY-MAP.md` to the right one if the repo has more than one).
