---
name: matt-grill-me
description: A relentless interview to sharpen a plan or design.
disable-model-invocation: true
---

## Freyja / Hermes compatibility

This is the `matt`-namespaced adaptation of the upstream `matt-grill-me` skill. Use Hermes-native tools and syntax; invoke sibling skills by their fully qualified `freyja-engineering:<skill-slug>` name. Do not assume a generic `Skill` tool exists. Honor current user authorization and do not expose secrets in logs, output, or artifacts.

Call the Hermes-native skill invocation `freyja-engineering:matt-grilling`.
