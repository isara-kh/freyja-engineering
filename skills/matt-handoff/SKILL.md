---
name: matt-handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

## Freyja / Hermes compatibility

This is the `matt`-namespaced adaptation of the upstream `matt-handoff` skill. Use Hermes-native tools and syntax; invoke sibling skills by their fully qualified `freyja-engineering:<skill-slug>` name. Do not assume a generic `Skill` tool exists. Honor current user authorization and do not expose secrets in logs, output, or artifacts.

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS - not the current workspace.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Hermes-native skill invocation for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
