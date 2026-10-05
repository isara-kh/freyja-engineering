# Hermes Agent Tool Mapping

Skills speak in actions ("dispatch a subagent", "create a todo", "read a file"). On Hermes Agent these resolve to the tools below.

## Tools

| Action skills request | Hermes tool |
|---|---|
| Read a file | `read_file({path: ...})` |
| Create or overwrite a file | `write_file({path: ..., content: ...})` |
| Edit a file (targeted patch) | `patch({path: ..., old_string: ..., new_string: ...})` |
| Run a shell command | `terminal({command: ..., workdir: ...})` |
| Search file contents or filenames | `search_files({pattern: ..., target: "content"|"files"})` |
| Fetch a URL / read a webpage | `web_extract({urls: [...]})` |
| Search the web | `web_search({query: ...})` |
| Dispatch a subagent | `delegate_task({goal: ..., context: ...})`; toolsets are inherited, not passed per child |
| Task tracking | `todo_list({action: "view"|"add"|"complete"|"remove", ...})` |
| Invoke a skill | `skill_view({name: "software-development:test-driven-development"})` |

## Instructions file

When a skill mentions "your instructions file," on Hermes Agent this is **`AGENTS.md`** in the project directory, or **`SOUL.md`** globally at `~/.hermes/SOUL.md`.

## Invoking a skill

Hermes Agent has a `skills` toolset with `skill_view` and `skills_list` tools.
To invoke a superpowers skill, use:

```
skill_view({name: "freyja-engineering:sp-brainstorming"})
skill_view({name: "freyja-engineering:sp-test-driven-development"})
```

If `skill_view` cannot find a superpowers skill (it may not appear in the catalog
until the plugin fully registers it), fall back to reading the SKILL.md directly:

```
read_file(path="~/.hermes/plugins/freyja-engineering/skills/<skill-name>/SKILL.md")
```

This fallback is the same mechanism used by other harnesses without native skill loading.

## Subagent dispatch

Use `delegate_task` to spawn isolated subagents; pass goal and context, while toolsets are inherited:

```
delegate_task({goal: ..., context: ...}) — toolsets are inherited, not passed per child
```

If `delegate_task` is unavailable, do the work inline rather than inventing tool calls.

## Task tracking

Use `todo_list` to view/add/complete/remove tasks in this session. For multi-agent task boards, use `hermes kanban` CLI if available. Treat older `TodoWrite` references as the task-tracking action.
