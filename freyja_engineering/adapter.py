"""Build and validate Freyja's pinned, namespaced skill bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PLUGIN_NAMESPACE = "freyja-engineering"
ADAPTER_VERSION = 1
_SIGNATURE_PATH = Path(__file__).parent / "data" / "adapter-signatures-v1.json"


class AdapterError(ValueError):
    """Invalid source inventory, unsafe file, or incompatible adapter anchor."""


def _signature_doc() -> Dict[str, Any]:
    try:
        document = json.loads(_SIGNATURE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AdapterError("Cannot load versioned adapter signature manifest") from exc
    if document.get("adapter_version") != ADAPTER_VERSION or not isinstance(document.get("signatures"), dict):
        raise AdapterError("Adapter signature manifest version/schema mismatch")
    return document


def _rel_dir(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise AdapterError("Skill directories must be non-empty repository-relative POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise AdapterError("Unsafe skill directory: {!r}".format(value))
    return path.as_posix()


def _inventory(lock: Mapping[str, Any]) -> Dict[str, List[str]]:
    if lock.get("schema_version") != 1 or lock.get("adapter_version") != ADAPTER_VERSION:
        raise AdapterError("Unsupported source lock or adapter version")
    sources = lock.get("sources")
    if not isinstance(sources, dict) or set(sources) != {"matt", "superpowers"}:
        raise AdapterError("Lock must define exactly matt and superpowers sources")
    result: Dict[str, List[str]] = {}
    for source, info in sources.items():
        if not isinstance(info, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(info.get("revision", ""))):
            raise AdapterError("{} source needs a full 40-character revision".format(source))
        skills = info.get("skills")
        if not isinstance(skills, list) or not skills:
            raise AdapterError("{} source must provide a non-empty skill inventory".format(source))
        dirs = [_rel_dir(item) for item in skills]
        if len(set(dirs)) != len(dirs):
            raise AdapterError("Duplicate {} skill inventory paths".format(source))
        if source == "matt" and any(not item.startswith("skills/") for item in dirs):
            raise AdapterError("Matt skill path must start with skills/")
        if source == "superpowers" and any(not item.startswith("skills/") for item in dirs):
            raise AdapterError("Superpowers skill path must start with skills/")
        result[source] = dirs
    if lock.get("sources", {}).get("matt", {}).get("repo") != "https://github.com/mattpocock/skills.git":
        raise AdapterError("Unexpected Matt source URL")
    if lock.get("sources", {}).get("superpowers", {}).get("repo") != "https://github.com/obra/superpowers.git":
        raise AdapterError("Unexpected Superpowers source URL")
    return result


def _safe_tree(base: Path, skill_dir: Path) -> None:
    if not skill_dir.is_dir() or skill_dir.is_symlink():
        raise AdapterError("Missing or symlinked skill directory: {}".format(skill_dir))
    try:
        skill_dir.resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise AdapterError("Skill directory escapes vendor root: {}".format(skill_dir)) from exc
    paths = list(skill_dir.rglob("*"))
    for path in paths:
        if path.is_symlink():
            raise AdapterError("Symlink in vendor skill tree: {}".format(path))
        try:
            path.resolve().relative_to(base.resolve())
        except ValueError as exc:
            raise AdapterError("Vendor path escapes root: {}".format(path)) from exc
        # Executable-bit assets remain inert: the adapter never invokes vendor code.


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_anchor(text: str, signature: Mapping[str, Any], label: str) -> Tuple[int, int]:
    anchor = signature["anchor"]
    if not isinstance(anchor, str) or not anchor:
        raise AdapterError("Invalid adapter signature anchor: {}".format(label))
    offset = 0
    matches = []
    while True:
        at = text.find(anchor, offset)
        if at < 0:
            break
        matches.append(at)
        offset = at + 1
    expected = signature.get("count", 1)
    if len(matches) != expected:
        raise AdapterError(
            "Adapter signature conflict for {}: expected {!r} {} time(s), found {}".format(
                label, anchor, expected, len(matches)
            )
        )
    start, end = matches[0], matches[0] + len(anchor)
    if _hash(anchor) != signature.get("sha256"):
        raise AdapterError("Adapter signature digest mismatch for {}".format(label))
    return start, end


def _all_source_docs(vendor_root: Path, inventory: Mapping[str, Sequence[str]]) -> Iterable[Tuple[str, str, Path, str]]:
    for source, dirs in inventory.items():
        source_root = vendor_root / source
        for rel in dirs:
            skill_root = source_root / Path(*PurePosixPath(rel).parts)
            _safe_tree(source_root, skill_root)
            skill_md = skill_root / "SKILL.md"
            if not skill_md.is_file():
                raise AdapterError("Missing SKILL.md: {}".format(skill_md))
            yield source, rel, skill_root, skill_md.read_text(encoding="utf-8")


def validate_adapter_signatures(
    vendor_root: Path, lock: Mapping[str, Any], signature_policy: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Check reviewed anchors; optional policy is an explicit test-fixture seam."""
    vendor_root = Path(vendor_root)
    inventory = _inventory(lock)
    policy = signature_policy if signature_policy is not None else _signature_doc()
    if policy.get("adapter_version") != ADAPTER_VERSION or not isinstance(policy.get("signatures"), dict):
        raise AdapterError("Adapter signature policy version/schema mismatch")
    signatures = policy["signatures"]
    findings: List[str] = []
    checked = 0
    docs = {(source, rel): text for source, rel, _skill, text in _all_source_docs(vendor_root, inventory)}
    for key, signature in signatures.items():
        if ":" not in key or not isinstance(signature, dict):
            findings.append("Malformed signature entry {!r}".format(key))
            continue
        source, rel = key.split(":", 1)
        display_key = key
        if source == "sp":
            source = "superpowers"
        if "#" in rel:
            rel, _suffix = rel.rsplit("#", 1)
        if rel not in inventory.get(source, ()):
            # Signatures apply to pinned source paths even when exercising a smaller fixture.
            continue
        text = docs.get((source, rel))
        if text is None:
            if source == "matt" and rel == "skills/engineering/improve-codebase-architecture":
                findings.append("Signature target missing from inventory: {}".format(display_key))
            elif source == "matt" and rel == "skills/engineering/wizard":
                findings.append("Signature target missing from inventory: {}".format(display_key))
            elif source == "superpowers" and rel in ("skills/systematic-debugging", "skills/subagent-driven-development"):
                findings.append("Signature target missing from inventory: {}".format(display_key))
            continue
        checked += 1
        try:
            _find_anchor(text, signature, display_key)
        except AdapterError as exc:
            findings.append(str(exc))
    sidecar_signatures = policy.get("sidecar_signatures", {})
    if not isinstance(sidecar_signatures, dict):
        findings.append("Malformed sidecar signature manifest")
    else:
        for key, signature in sidecar_signatures.items():
            try:
                source, rel, filename = key.split(":", 2)
                if source == "sp":
                    source = "superpowers"
                if "#" in filename:
                    filename = filename.split("#", 1)[0]
                if rel not in inventory.get(source, ()):
                    continue
                if not isinstance(signature, dict):
                    raise AdapterError("Malformed sidecar signature entry: " + key)
                path = vendor_root / source / rel / filename
                sidecar = path.read_text(encoding="utf-8")
                checked += 1
                _find_anchor(sidecar, signature, key)
            except (OSError, ValueError, AdapterError) as exc:
                findings.append("Sidecar signature conflict for {}: {}".format(key, exc))
    # Explicit fixture policy is limited to fixture signatures. Production builds
    # always use the checked-in manifest and its independently protected anchors.
    if signature_policy is None:
        for key, anchor, count in (
            ("matt:skills/engineering/wizard", "use `ask_secret` for anything secret", 1),
            ("matt:skills/engineering/wizard", "write_env` every persisted value", 1),
            ("sp:skills/systematic-debugging", '   echo "=== Secrets available in workflow: ==="', 1),
            ("sp:skills/systematic-debugging", 'env | grep IDENTITY || echo "IDENTITY not in environment"', 1),
            ("sp:skills/subagent-driven-development", "delete this plan's workspace (`rm -rf <workspace>`) — the git history is", 1),
        ):
            source, rel = key.split(":", 1)
            if source == "sp":
                source = "superpowers"
            if rel not in inventory.get(source, ()):
                continue
            text = docs.get((source, rel), "")
            checked += 1
            if text.count(anchor) != count:
                findings.append("Adapter signature conflict for {}: expected {!r} {} time(s), found {}".format(key, anchor, count, text.count(anchor)))
    return {"ok": not findings, "checked_signatures": checked, "findings": findings}


def _adapt_frontmatter(text: str, slug: str) -> str:
    if not text.startswith("---\n"):
        raise AdapterError("SKILL.md frontmatter must begin at byte zero")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AdapterError("SKILL.md frontmatter closing delimiter missing")
    header = text[4:end]
    names = list(re.finditer(r"(?m)^name:\s*([^\n]+)\s*$", header))
    if len(names) != 1:
        raise AdapterError("SKILL.md must have exactly one scalar name field")
    header = header[: names[0].start(1)] + slug + header[names[0].end(1) :]
    return "---\n" + header + text[end:]


def _replace_links(text: str, source: str, rel: str, rel_to_slug: Mapping[Tuple[str, str], str]) -> str:
    link = re.compile(r"(?P<prefix>\]\()(?P<target>[^)]+)(?P<suffix>\))")

    def replace(match: re.Match[str]) -> str:
        target = match.group("target")
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return match.group(0)
        path_part, sep, fragment = target.partition("#")
        path = PurePosixPath(path_part)
        if path.is_absolute():
            raise AdapterError("Unsafe absolute Markdown support reference: {}".format(target))
        resolved_parts = list(PurePosixPath(rel).parts)
        for part in path.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not resolved_parts:
                    raise AdapterError("Unsafe relative Markdown link {} in {}".format(target, rel))
                resolved_parts.pop()
            else:
                resolved_parts.append(part)
        resolved = PurePosixPath(*resolved_parts)
        for (origin, skill_rel), slug in rel_to_slug.items():
            skill_path = PurePosixPath(skill_rel)
            if origin == source and (resolved == skill_path or skill_path in resolved.parents):
                rest = resolved.relative_to(skill_path)
                rewritten = (PurePosixPath("skills") / slug / rest).as_posix()
                if sep:
                    rewritten += "#" + fragment
                return match.group("prefix") + rewritten + match.group("suffix")
        return match.group(0)

    return link.sub(replace, text)


def _rewrite_refs(text: str, source: str, rel_to_slug: Mapping[Tuple[str, str], str]) -> str:
    adapted = text
    # Hard-coded tool invocations are mapped to Hermes-native namespaced syntax.
    for (origin, rel), slug in rel_to_slug.items():
        if origin != source:
            continue
        old = rel.rsplit("/", 1)[-1]
        tool_pattern = re.compile(r"(?i)Skill tool")
        adapted = tool_pattern.sub("Hermes-native skill invocation", adapted)
        invocation = re.compile(r"(?i)(?:with)\s+([\"'`])" + re.escape(old) + r"\1")
        adapted = invocation.sub("`" + PLUGIN_NAMESPACE + ":" + slug + "`", adapted)
    return adapted


def _rewrite_namespaced_workflows(text: str, rel_to_slug: Mapping[Tuple[str, str], str]) -> str:
    """Qualify known Superpowers skill names in prose and slash workflows."""
    slugs = {PurePosixPath(rel).name: slug for (source, rel), slug in rel_to_slug.items() if source == "superpowers"}
    for old, slug in sorted(slugs.items(), key=lambda item: -len(item[0])):
        qualified = PLUGIN_NAMESPACE + ":" + slug
        text = re.sub(r"(?<=/)" + re.escape(old) + r"(?=/)", qualified.rsplit(":", 1)[-1], text)
        text = text.replace("superpowers:" + old, qualified)
        text = text.replace("/" + old, qualified)
    return text


def _adapt_architecture_report(text: str) -> str:
    """Make the report scaffold inert while retaining its teaching content."""
    anchor = "The architectural review is rendered as a single self-contained HTML file in the OS temp directory."
    if text.count(anchor) != 1:
        raise AdapterError("Architecture report sidecar signature conflict")
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script\s*>", "<!-- Remote and inline scripts removed; render diagrams as escaped static text. -->", text)
    text = text.replace("securityLevel: \"loose\"", "")
    text = text.replace('<pre class="mermaid">', '<pre class="static-diagram">')
    text = text.replace("Tailwind and Mermaid both come from CDNs.", "The report is rendered without remote scripts or CDNs; Mermaid syntax is shown only as escaped static text.")
    text = text.replace("The only scripts are the Tailwind CDN and the Mermaid ESM import. The report is otherwise static: no app code, no interactivity beyond Mermaid's own rendering.", "The report is static: no scripts, remote assets, or runtime diagram rendering. Escape project-derived text before placing it in HTML; show Mermaid syntax as escaped plain text.")
    text = text.replace("securityLevel: \\\"loose\\\"", "")
    text = text.replace("Mermaid handles graph-shaped diagrams reliably;", "Escaped Mermaid text documents graph-shaped diagrams;")
    text = text.replace("Use a Mermaid `flowchart` or `graph`", "Show escaped Mermaid `flowchart` or `graph` source as static text")
    return text


def _adapt_wizard_template(text: str) -> str:
    """Require a live human confirmation for every persistent write."""
    anchors = ("set -euo pipefail", "write_env() {", "set_secret() {", "set_var() {")
    for anchor in anchors:
        if text.count(anchor) != 1:
            raise AdapterError("Wizard persistence sidecar signature conflict: {}".format(anchor))
    text = text.replace("set -euo pipefail", "set -euo pipefail\numask 077\n")
    helper = '''# Persistence is never allowed from a non-interactive run. Each target/value requires explicit confirmation from a human.
_authorize_write() {
  [[ -t 0 ]] || { warn "refusing persistence without an interactive terminal"; return 1; }
  confirm "$1" || { warn "write declined"; return 1; }
}

'''
    text = text.replace("write_env() {", helper + "write_env() {")
    text = text.replace('  local key="$1" value="$2" tmp\n  touch "$ENV_FILE"', '  local key="$1" value="$2" tmp\n  _authorize_write "Write $key to exact file $ENV_FILE?" || return 1\n  [[ ! -L "$ENV_FILE" ]] || { warn "refusing symlinked env file: $ENV_FILE"; return 1; }\n  touch "$ENV_FILE"\n  chmod 600 "$ENV_FILE"')
    text = text.replace('  tmp=$(mktemp)\n  grep -vE', '  tmp=$(mktemp "${ENV_FILE}.tmp.XXXXXX")\n  grep -vE')
    text = text.replace('  printf \'%s=%s\\n\' "$key" "$value" >> "$tmp"\n  mv "$tmp" "$ENV_FILE"', '  printf \'%s=%s\\n\' "$key" "$value" >> "$tmp"\n  chmod 600 "$tmp"\n  mv "$tmp" "$ENV_FILE"\n  chmod 600 "$ENV_FILE"')
    text = text.replace('  local name="$1" value="$2"\n  if command -v gh', '  local name="$1" value="$2"\n  _authorize_write "Set GitHub Actions secret $name in the current repository?" || return 1\n  if command -v gh', 1)
    text = text.replace('  local name="$1" value="$2"\n  if command -v gh', '  local name="$1" value="$2"\n  _authorize_write "Set GitHub Actions variable $name in the current repository?" || return 1\n  if command -v gh', 1)
    if text.count("_authorize_write ") != 3:
        raise AdapterError("Wizard persistence confirmation adaptation did not cover every writer")
    return text


def _adapt_finishing_cleanup(text: str) -> str:
    anchor = "**If `WORKTREE_PATH` is under `.worktrees/` or `worktrees/`:** Superpowers"
    if text.count(anchor) != 1:
        raise AdapterError("Finishing cleanup ownership anchor conflict")
    text = text.replace(anchor, "**A `.worktrees/` or `worktrees/` location does not establish ownership.**")
    old = "created this worktree — we own cleanup:\n\n```bash\ngit worktree remove \"$WORKTREE_PATH\"\ngit worktree prune  # Self-healing: clean up any stale registrations\n```"
    new = "location is only a hint, never proof of ownership. Preserve the workspace unless BOTH conditions hold: (1) a creation receipt from this workflow records the exact canonical `WORKTREE_PATH` and its unique worktree identity; and (2) the human partner gives explicit scoped authorization to remove that exact path after seeing its status. No receipt, mismatched path/identity, or no authorization means preserve it. Never prune unrelated worktrees. After both checks, remove only the receipted exact path:\n\n```bash\ngit worktree remove \"$WORKTREE_PATH\"\n```"
    if old not in text:
        raise AdapterError("Finishing cleanup command anchor conflict")
    return text.replace(old, new)


def _adapt_tool_map(text: str) -> str:
    anchor = '| Dispatch a subagent | `delegate_task(goal=..., context=..., toolsets=[...], role="leaf")` |'
    if anchor not in text:
        raise AdapterError("Hermes tool map signature conflict")
    start, end = text.index("## Tools"), text.index("## Instructions file")
    table = '''## Tools

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

'''
    text = text[:start] + table + text[end:]
    text = text.replace('skill_view("brainstorming")', 'skill_view({name: "freyja-engineering:sp-brainstorming"})')
    text = text.replace('skill_view("test-driven-development")', 'skill_view({name: "freyja-engineering:sp-test-driven-development"})')
    text = text.replace('~/.hermes/plugins/superpowers/skills/<skill-name>/SKILL.md', '~/.hermes/plugins/freyja-engineering/skills/<skill-name>/SKILL.md')
    text = text.replace('delegate_task(goal="...", context="...", toolsets=[...], role="leaf")', 'delegate_task({goal: ..., context: ...}) — toolsets are inherited, not passed per child')
    text = text.replace('Use `delegate_task` to spawn isolated subagents for parallel or sequential workstreams:', 'Use `delegate_task` to spawn isolated subagents; pass goal and context, while toolsets are inherited:')
    text = text.replace('Use the `todo` tool for task tracking within a session.', 'Use `todo_list` to view/add/complete/remove tasks in this session.')
    text = text.replace('created this worktree — we own cleanup:', 'location is only a hint, never proof of ownership. Preserve it without a creation receipt for this exact path and explicit scoped authorization to remove the exact path:')
    return text


def _adapt_sidecar(source: str, rel: str, path: Path, text: str) -> str:
    if source == "matt" and rel == "skills/engineering/improve-codebase-architecture" and path.name == "HTML-REPORT.md":
        return _adapt_architecture_report(text)
    if source == "matt" and rel == "skills/engineering/wizard" and path.name == "template.sh":
        return _adapt_wizard_template(text)
    if source == "superpowers" and rel == "skills/finishing-a-development-branch" and path.name == "SKILL.md":
        return _adapt_finishing_cleanup(text)
    if source == "superpowers" and rel == "skills/using-superpowers" and path.as_posix().endswith("references/hermes-tools.md"):
        return _adapt_tool_map(text)
    return text


def _security_adapt(source: str, rel: str, text: str) -> str:
    signatures = _signature_doc()["signatures"]
    if source == "matt" and rel.startswith("skills/engineering/improve-codebase-architecture"):
        signature = signatures["matt:skills/engineering/improve-codebase-architecture"]
        start, end = _find_anchor(text, signature, "matt:skills/engineering/improve-codebase-architecture")
        text = text[:start] + signature["replacement"] + text[end:]
    if source == "matt" and rel == "skills/engineering/wizard":
        # Fail closed if wizard secret-related implementation guidance changed.
        if "use `ask_secret` for anything secret" not in text or "write_env` every persisted value" not in text:
            raise AdapterError("Wizard secret-handling semantic anchor conflict")
        text = text.replace("use `ask_secret` for anything secret", "use `ask_secret` for anything secret; never persist until the human explicitly confirms the exact destination and write")
        text = text.replace("write_env` every persisted value", "write_env` only after explicit confirmation in an interactive terminal; set umask 077 and mode 0600 on persisted files; confirm GitHub writes individually")
    if source == "superpowers" and rel == "skills/systematic-debugging":
        anchor = '   echo "=== Secrets available in workflow: ==="'
        if text.count(anchor) != 1:
            raise AdapterError("Debugging secret-output anchor conflict")
        text = text.replace(anchor, '   # List names only; never print workflow secret values.')
        env_anchor = 'env | grep IDENTITY || echo "IDENTITY not in environment"'
        signature = _signature_doc()["signatures"]["sp:skills/systematic-debugging#identity-env"]
        _find_anchor(text, signature, "sp:skills/systematic-debugging#identity-env")
        text = text.replace(env_anchor, 'if [ "${IDENTITY+x}" = x ]; then printf "IDENTITY is set\\n"; else printf "IDENTITY not in environment\\n"; fi')
    if source == "superpowers" and rel == "skills/subagent-driven-development":
        anchor = "delete this plan's workspace (`rm -rf <workspace>`) — the git history is"
        if text.count(anchor) != 1:
            raise AdapterError("Workspace cleanup ownership anchor conflict")
        text = text.replace(anchor, "delete only this plan's verified, exclusively-owned workspace (never use a broad recursive delete) — the git history is")
    if source == "superpowers" and rel == "skills/using-git-worktrees":
        # This checked-out upstream revision documents setup only; do not patch an absent cleanup command.
        if "git worktree remove" in text:
            text = text.replace(
                "git worktree remove",
                "verify exact generated worktree path and uncommitted contents before `git worktree remove`",
            )
    return text


def _add_policy(text: str, source: str, slug: str) -> str:
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AdapterError("Frontmatter delimiter missing")
    policy = (
        "\n## Freyja / Hermes compatibility\n\n"
        "This is the `{}`-namespaced adaptation of the upstream `{}` skill. "
        "Use Hermes-native tools and syntax; invoke sibling skills by their fully qualified "
        "`freyja-engineering:<skill-slug>` name. Do not assume a generic `Skill` tool exists. "
        "Interview and grilling skills (`matt-grill-me`, `matt-grilling`, `matt-grill-with-docs`) are explicit "
        "opt-in only: never auto-load them before implement or brainstorming, and never treat a meta question "
        "about grilling as a request. "
        "Honor current user authorization and do not expose secrets in logs, output, or artifacts.\n"
    ).format(source, slug)
    return text[: end + 5] + policy + text[end + 5 :]


def _slug(source: str, rel: str) -> str:
    leaf = PurePosixPath(rel).name
    return ("matt-" if source == "matt" else "sp-") + leaf


def _link_map(inventory: Mapping[str, Sequence[str]]) -> Dict[Tuple[str, str], str]:
    return {(source, rel): _slug(source, rel) for source, dirs in inventory.items() for rel in dirs}


def _rewrite_local_links(text: str, source: str, rel: str, inventory: Mapping[str, Sequence[str]]) -> str:
    current = PurePosixPath(rel)
    by_dir = {(src, PurePosixPath(item)): _slug(src, item) for src, paths in inventory.items() for item in paths}

    def replace(match: re.Match[str]) -> str:
        target = match.group("target")
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return match.group(0)
        path_part, sep, fragment = target.partition("#")
        if not path_part:
            return match.group(0)
        path = PurePosixPath(path_part)
        if path.is_absolute():
            raise AdapterError("Unsafe relative Markdown link {} in {}".format(target, rel))
        resolved_parts = list(current.parts)
        for part in path.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not resolved_parts:
                    raise AdapterError("Unsafe relative Markdown link {} in {}".format(target, rel))
                resolved_parts.pop()
            else:
                resolved_parts.append(part)
        resolved = PurePosixPath(*resolved_parts)
        for (origin, skill_dir), slug in by_dir.items():
            if origin == source and (resolved == skill_dir or skill_dir in resolved.parents):
                inner = resolved.relative_to(skill_dir)
                rewritten = (PurePosixPath("..") / slug / inner).as_posix()
                if sep:
                    rewritten += "#" + fragment
                return match.group("pre") + rewritten + match.group("post")
        return match.group(0)

    return re.sub(r"(?P<pre>\]\()(?P<target>[^)]+)(?P<post>\))", replace, text)


def _copy_tree(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        dest = target / rel
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            shutil.copystat(path, dest, follow_symlinks=False)
        else:
            raise AdapterError("Unsupported vendor object: {}".format(path))


def _copy_adapted_tree(source: Path, target: Path, origin: str, rel: str, rel_to_slug: Mapping[Tuple[str, str], str]) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        dest = target / relative
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() in (".md", ".txt", ".sh", ".yaml", ".yml", ".json"):
                text = path.read_text(encoding="utf-8")
                text = _adapt_sidecar(origin, rel, path, text)
                text = _rewrite_namespaced_workflows(text, rel_to_slug)
                dest.write_text(text, encoding="utf-8")
                shutil.copystat(path, dest, follow_symlinks=False)
            else:
                shutil.copyfile(path, dest)
                shutil.copystat(path, dest, follow_symlinks=False)
        else:
            raise AdapterError("Unsupported vendor object: {}".format(path))


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---\n"):
        raise AdapterError("Frontmatter must start at first byte")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise AdapterError("Frontmatter closing delimiter missing")
    raw = text[4:end]
    fields = {}
    for line in raw.splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise AdapterError("Unsupported frontmatter line: {}".format(line))
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields, text[end + 5 :]


def validate_bundle(output_root: Path, lock: Mapping[str, Any]) -> Dict[str, Any]:
    """Exhaustively verify inventory, frontmatter, and every relative Markdown link."""
    output_root = Path(output_root)
    inventory = _inventory(lock)
    expected = {_slug(source, rel) for source, paths in inventory.items() for rel in paths}
    skill_root = output_root / "skills" if (output_root / "skills").is_dir() else output_root
    actual = {p.name for p in skill_root.iterdir() if p.is_dir()} if skill_root.exists() else set()
    findings: List[str] = []
    vendor_root = output_root.parent / "vendor"
    for missing in sorted(expected - actual):
        findings.append("Missing generated skill directory: {}".format(missing))
    for extra in sorted(actual - expected):
        findings.append("Unexpected generated skill directory: {}".format(extra))
    seen_docs = 0
    for source, rels in inventory.items():
        for rel in rels:
            slug = _slug(source, rel)
            directory = skill_root / slug
            if directory.is_symlink():
                findings.append("Generated skill directory is a symlink: {}".format(slug))
                continue
            if not directory.is_dir():
                continue
            for child in directory.rglob("*"):
                if child.is_symlink():
                    findings.append("Generated symlink: {}".format(child))
                    continue
                try:
                    child.resolve().relative_to(output_root.resolve())
                except ValueError:
                    findings.append("Generated artifact escapes output root: {}".format(child))
            seen_docs += 1
            document = directory / "SKILL.md"
            if not document.is_file():
                findings.append("Missing SKILL.md: {}".format(slug))
                continue
            text = document.read_text(encoding="utf-8")
            try:
                fields, body = _parse_frontmatter(text)
                if fields.get("name") != slug:
                    findings.append("Wrong frontmatter name in {}".format(slug))
                if not fields.get("description"):
                    findings.append("Missing description in {}".format(slug))
                if not body.strip():
                    findings.append("Empty body in {}".format(slug))
                if re.search(r"(?i)(?:call the )Skill tool\b", body):
                    findings.append("Obsolete generic Skill tool example in {}".format(slug))
                if re.search(r"Skill tool with\s+[\"'`]", body):
                    findings.append("Obsolete invocation syntax in {}".format(slug))
                if source == "matt" and rel.startswith("skills/engineering/improve-codebase-architecture"):
                    if "Tailwind via CDN" in body or "Mermaid via CDN" in body:
                        findings.append("Unsafe CDN report default remains in {}".format(slug))
            except AdapterError as exc:
                findings.append("{}: {}".format(slug, exc))
            for path in directory.rglob("*"):
                if path.is_symlink():
                    findings.append("Generated symlink: {}".format(path))
                elif path.is_file() and path.suffix.lower() in (".md", ".txt", ".sh", ".yaml", ".yml", ".json"):
                    content = path.read_text(encoding="utf-8")
                    relative = path.relative_to(skill_root).as_posix()
                    if source == "matt" and rel == "skills/engineering/improve-codebase-architecture" and path.name == "HTML-REPORT.md":
                        if re.search(r"(?is)<script\b|https?://[^ ]*cdn|securityLevel:\s*['\"]loose", content):
                            findings.append("Unsafe report script/CDN/loose-rendering marker in {}".format(relative))
                        if '<pre class="mermaid">' in content:
                            findings.append("Active Mermaid block remains in {}".format(relative))
                    if source == "matt" and rel == "skills/engineering/wizard" and path.name == "template.sh":
                        for marker in ("umask 077", "[[ -t 0 ]]", "_authorize_write", "chmod 600"):
                            if marker not in content:
                                findings.append("Wizard persistence safety marker missing ({}) in {}".format(marker, relative))
                    if source == "superpowers" and rel == "skills/finishing-a-development-branch" and path.name == "SKILL.md":
                        if "creation receipt" not in content.lower() or "explicit scoped authorization" not in content.lower() or "exact path" not in content.lower():
                            findings.append("Cleanup ownership receipt/authorization guard missing in {}".format(relative))
                    if source == "superpowers" and rel == "skills/using-superpowers" and path.name == "hermes-tools.md":
                        for marker in ("delegate_task({goal: ..., context: ...})", "todo_list", "search_files"):
                            if marker not in content:
                                findings.append("Stale or incomplete Hermes tool map in {}".format(relative))
                        if "toolsets=[...], role=\"leaf\"" in content or "terminal` with `find`" in content or "| Task tracking | `todo` tool" in content:
                            findings.append("Stale Hermes tool signature in {}".format(relative))
                    if re.search(r"(?i)\bsuperpowers:[a-z0-9][a-z0-9-]*", content):
                        findings.append("Unresolved legacy Superpowers namespace reference in {}".format(relative))
                    if source == "superpowers" and re.search(r"(?i)(?:`|/)superpowers:[a-z0-9][a-z0-9-]*", content):
                        findings.append("Unresolved legacy slash workflow reference in {}".format(relative))
                    for match in re.finditer(r"\]\(([^)]+)\)", content):
                        target = match.group(1).split("#", 1)[0]
                        if target.startswith(("http://", "https://", "mailto:")) or not target:
                            continue
                        target_path = (path.parent / target).resolve()
                        try:
                            target_path.relative_to(skill_root.resolve())
                        except ValueError:
                            findings.append("Escaping support reference {} in {}".format(target, relative))
                            continue
                        if not target_path.exists():
                            allowed_upstream_reference = (
                                (source == "matt" and rel == "skills/engineering/wayfinder" and (target == "link" or target.endswith("/link")))
                                or (source == "matt" and rel == "skills/engineering/domain-modeling" and target.startswith("./src/"))
                                or (source == "superpowers" and rel == "skills/writing-skills" and "anthropic-best-practices.md" in relative)
                            )
                            if not allowed_upstream_reference:
                                for source_name in inventory:
                                    if any(
                                        (vendor_root / source_name / skill_rel / target).exists()
                                        for skill_rel in inventory[source_name]
                                    ):
                                        allowed_upstream_reference = True
                                        break
                            if not allowed_upstream_reference:
                                findings.append("Dangling support reference {} in {}".format(target, relative))
    return {"ok": not findings, "skill_count": seen_docs, "expected_skill_count": len(expected), "findings": findings}


def build_bundle(
    vendor_root: Path, output_root: Path, lock: Mapping[str, Any],
    *, signature_policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a fresh generated tree; refuses non-empty destinations and unsafe inputs."""
    vendor_root, output_root = Path(vendor_root), Path(output_root)
    inventory = _inventory(lock)
    signatures = validate_adapter_signatures(vendor_root, lock, signature_policy=signature_policy)
    if not signatures["ok"]:
        raise AdapterError("Adapter signature conflict: " + "; ".join(signatures["findings"]))
    for source in inventory:
        if not (vendor_root / source / "LICENSE").is_file():
            raise AdapterError("Missing preserved upstream license for {}".format(source))
    if output_root.exists() and (not output_root.is_dir() or any(output_root.iterdir())):
        raise AdapterError("Output directory must be absent or empty: {}".format(output_root))
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".freyja-adapter-", dir=str(output_root.parent)))
    try:
        generated = staging / "skills"
        generated.mkdir()
        link_map = _link_map(inventory)
        count = 0
        for source, rel, skill_dir, original in _all_source_docs(vendor_root, inventory):
            slug = _slug(source, rel)
            target = generated / slug
            target.mkdir(parents=True)
            _copy_adapted_tree(skill_dir, target, source, rel, link_map)
            adapted = _adapt_frontmatter(original, slug)
            adapted = _adapt_sidecar(source, rel, skill_dir / "SKILL.md", adapted)
            adapted = _security_adapt(source, rel, adapted)
            adapted = _rewrite_refs(adapted, source, link_map)
            adapted = _rewrite_namespaced_workflows(adapted, link_map)
            adapted = _rewrite_local_links(adapted, source, rel, inventory)
            adapted = _add_policy(adapted, source, slug)
            (target / "SKILL.md").write_text(adapted, encoding="utf-8")
            count += 1
        for source in inventory:
            license_src = vendor_root / source / "LICENSE"
            license_dest = staging / "vendor" / source / "LICENSE"
            license_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(license_src, license_dest)
        receipt = {
            "schema_version": 1,
            "adapter_version": ADAPTER_VERSION,
            "plugin_namespace": PLUGIN_NAMESPACE,
            "sources": {key: {"revision": lock["sources"][key]["revision"], "skill_count": len(paths)} for key, paths in inventory.items()},
            "skill_count": count,
            "signature_count": signatures["checked_signatures"],
        }
        (staging / "build.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validation = validate_bundle(staging, lock)
        if not validation["ok"]:
            raise AdapterError("Generated bundle failed validation: " + "; ".join(validation["findings"]))
        if output_root.exists():
            output_root.rmdir()
        os.replace(str(staging), str(output_root))
        return receipt
    finally:
        if staging.exists():
            shutil.rmtree(staging)
