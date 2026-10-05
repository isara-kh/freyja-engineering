"""Fail-closed, manual updater for the generated Freyja skill bundle.

Nothing in this module runs at plugin startup. Network access happens only in
``check`` and ``update``; all fetched Git content is pinned and treated as data.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple


class UpdateError(RuntimeError):
    """An update was rejected or could not be safely completed."""


ALLOWED_REPOSITORIES = {
    "matt": "https://github.com/mattpocock/skills.git",
    "superpowers": "https://github.com/obra/superpowers.git",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
GENERATION_RE = re.compile(r"^gen-[0-9a-f]{32}$")
SUPPORTED_ADAPTER_VERSION = 1


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Cannot read valid JSON: " + str(path)) from exc


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temp), str(path))
        try:
            fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_tree(root: Path) -> None:
    """Reject any symlink/special file and ensure regular tree paths stay inside root."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise UpdateError("Unsafe or missing tree: " + str(root))
    base = root.resolve()
    for current, dirs, files in os.walk(str(root), followlinks=False):
        current_path = Path(current)
        for name in list(dirs) + list(files):
            item = current_path / name
            try:
                mode = item.lstat().st_mode
            except OSError as exc:
                raise UpdateError("Cannot inspect candidate path: " + str(item)) from exc
            if stat.S_ISLNK(mode):
                raise UpdateError("Symbolic links are not allowed in upstream content: " + str(item))
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise UpdateError("Special files are not allowed in upstream content: " + str(item))
            resolved = item.resolve()
            if not resolved.is_relative_to(base):
                raise UpdateError("Path escapes upstream tree: " + str(item))


def _safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise UpdateError("Invalid repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise UpdateError("Unsafe repository path: " + value)
    return path


def _validate_lock(lock: dict) -> None:
    if not isinstance(lock, dict) or lock.get("schema_version") != 1:
        raise UpdateError("Unsupported upstream lock schema")
    if lock.get("adapter_version") != SUPPORTED_ADAPTER_VERSION:
        raise UpdateError("Unsupported adapter version in upstream lock")
    sources = lock.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(ALLOWED_REPOSITORIES):
        raise UpdateError("Lock must contain exactly the supported upstream sources")
    for name, url in ALLOWED_REPOSITORIES.items():
        source = sources.get(name)
        if not isinstance(source, dict) or source.get("repo") != url:
            raise UpdateError("Disallowed upstream repository for " + name)
        if not SHA_RE.fullmatch(str(source.get("revision", ""))):
            raise UpdateError("Invalid pinned revision for " + name)
        skills = source.get("skills")
        if not isinstance(skills, list) or not skills or len(skills) != len(set(skills)):
            raise UpdateError("Invalid skill inventory for " + name)
        prefix = "skills/"
        for skill in skills:
            rel = _safe_relative(skill)
            if not skill.startswith(prefix) or len(rel.parts) < (3 if name == "matt" else 2):
                raise UpdateError("Skill path outside supported inventory root: " + str(skill))


def _manifest_names(plugin_root: Path) -> set:
    """Read the active plugin skill inventory, not arbitrary local Hermes skills."""
    names = set()
    manifest = plugin_root / "plugin.yaml"
    if manifest.is_file() and not manifest.is_symlink():
        text = manifest.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^\s*-\s*['\"]?((?:matt|sp)-[a-z0-9][a-z0-9_-]*)['\"]?\s*(?:#.*)?$", text):
            names.add(match.group(1))
    bundled = plugin_root / "skills"
    if bundled.is_dir() and not bundled.is_symlink():
        for entry in bundled.iterdir():
            if entry.is_dir() and not entry.is_symlink() and re.fullmatch(r"(?:matt|sp)-[a-z0-9][a-z0-9_-]*", entry.name):
                names.add(entry.name)
    return names


def _skill_dirs(tree_root: Path) -> List[str]:
    """Find SKILL.md directories under supported source inventory roots."""
    if tree_root.is_symlink() or not tree_root.is_dir():
        raise UpdateError("Missing or unsafe source tree")
    result = []
    for current, dirs, files in os.walk(str(tree_root), followlinks=False):
        here = Path(current)
        if "SKILL.md" in files:
            rel = here.relative_to(tree_root).as_posix()
            if rel.startswith("skills/"):
                result.append(rel)
    return sorted(result)


def _matt_promoted_inventory(tree: Path) -> List[str]:
    """Use Matt's own promoted-skill manifest as the authoritative source."""
    manifest = tree / ".claude-plugin" / "plugin.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise UpdateError("Matt promoted-skill manifest is missing or unsafe")
    data = _json(manifest)
    declared = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(declared, list) or not declared:
        raise UpdateError("Matt promoted-skill manifest has no valid skills inventory")
    inventory = []
    for value in declared:
        if not isinstance(value, str):
            raise UpdateError("Invalid path in Matt promoted-skill manifest")
        value = value[2:] if value.startswith("./") else value
        relative = _safe_relative(value).as_posix()
        if not relative.startswith("skills/") or len(PurePosixPath(relative).parts) < 3:
            raise UpdateError("Matt promoted-skill path is outside the supported roots")
        inventory.append(relative)
    if len(set(inventory)) != len(inventory):
        raise UpdateError("Duplicate Matt promoted-skill manifest entry")
    return sorted(inventory)


class _FileLock:
    def __init__(self, path: Path, timeout: float = 60.0):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, (str(os.getpid()) + "\n").encode("ascii"))
                os.fsync(self.fd)
                return self
            except FileExistsError:
                try:
                    pid_text = self.path.read_text(encoding="ascii").strip()
                    pid = int(pid_text)
                    os.kill(pid, 0)
                except ProcessLookupError:
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                except (ValueError, OSError):
                    # A partially-created/live lock is never stolen on a guess.
                    pass
                if time.monotonic() >= deadline:
                    raise UpdateError("Timed out waiting for updater lock")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _scanner_report(scanner_module: Any, path: Path) -> dict:
    result = scanner_module.scan_skill(path, source="community")
    return {"verdict": result.verdict, "findings": result.findings}
class BundleManager:
    """Check, stage, apply, inspect, or rollback one verified bundle generation.

    ``revision_resolver``, ``fetcher`` and ``scanner`` are dependency injection
    points for local fixture tests. The CLI does not expose them. Repositories
    remain allowlisted even when these test seams are supplied.
    """

    def __init__(self, plugin_root: Path, state_root: Optional[Path] = None, *,
                 revision_resolver: Optional[Callable[[str], str]] = None,
                 fetcher: Optional[Callable[[str, str], Path]] = None,
                 scanner: Optional[Callable[[Path], Any]] = None,
                 adapter: Optional[Callable[[Path, Path, dict], Tuple[dict, dict]]] = None):
        self.plugin_root = Path(plugin_root).expanduser().absolute()
        if self.plugin_root.is_symlink() or not self.plugin_root.is_dir():
            raise UpdateError("Plugin root must be an existing, non-symlink directory")
        default_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
        self.state_root = Path(state_root).expanduser().absolute() if state_root else default_home / "plugin-data" / "freyja-engineering"
        if self.state_root == self.plugin_root or self.plugin_root in self.state_root.parents:
            raise UpdateError("Runtime state must live outside the tracked plugin tree")
        if self.state_root in self.plugin_root.parents:
            raise UpdateError("Runtime state root cannot contain the tracked plugin tree")
        if self.state_root.exists() and (self.state_root.is_symlink() or not self.state_root.is_dir()):
            raise UpdateError("State root must be a non-symlink directory")
        self.revision_resolver = revision_resolver
        self.fetcher = fetcher
        self.scanner = scanner
        self.adapter = adapter

    def _lock(self) -> dict:
        self._validate_state_root()
        lock = None
        if self.state_root.exists():
            state = self._read_state(allow_missing=True)
            if state and state.get("current"):
                lock = state["current"].get("lock")
        if lock is None:
            lock = _json(self.plugin_root / "upstream.lock.json")
        _validate_lock(lock)
        return lock

    def _validate_state_root(self) -> None:
        if self.state_root.is_symlink():
            raise UpdateError("State root must not be a symbolic link")
        if self.state_root.exists() and not self.state_root.is_dir():
            raise UpdateError("State root must be a directory")

    @staticmethod
    def _git(args: List[str], cwd: Optional[Path] = None) -> str:
        env = dict(os.environ)
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
        try:
            for key in list(env):
                if key.startswith("GIT_CONFIG_"):
                    env.pop(key, None)
            for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES", "GIT_COMMON_DIR"):
                env.pop(key, None)
            env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "0"})
            result = subprocess.run(["git"] + args, cwd=str(cwd) if cwd else None, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True,
                                    timeout=120)
        except OSError as exc:
            raise UpdateError("Git is required for manual source updates") from exc
        except subprocess.TimeoutExpired as exc:
            raise UpdateError("Git operation timed out") from exc
        if result.returncode:
            raise UpdateError("Git operation failed: " + result.stderr.strip()[-500:])
        return result.stdout.strip()

    def _latest(self, name: str) -> str:
        if self.revision_resolver:
            value = self.revision_resolver(name)
            if not SHA_RE.fullmatch(str(value)):
                raise UpdateError("Revision resolver returned an invalid SHA")
            return value
        url = ALLOWED_REPOSITORIES[name]
        output = self._git(["ls-remote", url, "refs/heads/main"])
        lines = [line.split() for line in output.splitlines() if line.split()]
        if len(lines) != 1 or len(lines[0]) != 2 or lines[0][1] != "refs/heads/main" or not SHA_RE.fullmatch(lines[0][0]):
            raise UpdateError("Could not resolve the allowlisted main branch for " + name)
        return lines[0][0]

    def _verify_git_revision(self, repo: Path, revision: str) -> None:
        actual = self._git(["rev-parse", "HEAD"], cwd=repo)
        if actual != revision:
            raise UpdateError("Fetched fixture revision does not match pinned SHA")
        try:
            listing = subprocess.run(
                ["git", "ls-tree", "-r", "-z", revision], cwd=str(repo), check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError("Could not verify pinned Git tree") from exc
        for entry in listing.split(b"\x00"):
            if not entry:
                continue
            try:
                metadata, _path = entry.split(b"\t", 1)
            except ValueError as exc:
                raise UpdateError("Malformed Git tree listing") from exc
            fields = metadata.decode("ascii").split()
            if len(fields) >= 2 and fields[0] == "120000" and _path.startswith(b"skills/"):
                raise UpdateError("Pinned Git content contains a symbolic link in skill content")

    def _fetch(self, name: str, revision: str, download_root: Path) -> Path:
        if self.fetcher:
            path = Path(self.fetcher(name, revision)).absolute()
            if path.is_symlink() or not path.is_dir():
                raise UpdateError("Injected fixture fetcher returned an unsafe directory")
            self._verify_git_revision(path, revision)
            _safe_tree(path / "skills")
            return path
        repo = download_root / (name + "-repo")
        repo.mkdir(mode=0o700)
        self._git(["init", "--quiet", str(repo)])
        url = ALLOWED_REPOSITORIES[name]
        self._git(["-C", str(repo), "fetch", "--quiet", "--no-tags", "--depth=1", url, revision])
        actual = self._git(["-C", str(repo), "rev-parse", "FETCH_HEAD^{commit}"])
        if actual != revision:
            raise UpdateError("Fetched commit does not match requested SHA")
        archive_file = download_root / (name + ".tar")
        with archive_file.open("wb") as stream:
            result = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", revision],
                                    stdout=stream, stderr=subprocess.PIPE, check=False,
                                    env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                                         "GIT_CONFIG_COUNT": "0", "GIT_TERMINAL_PROMPT": "0"}, timeout=120)
        if result.returncode:
            raise UpdateError("Could not archive pinned Git content")
        extracted = download_root / (name + "-tree")
        extracted.mkdir(mode=0o700)
        _extract_tar_safely(archive_file, extracted)
        _safe_tree(extracted / "skills")
        return extracted

    def _inventory(self, name: str, root: Path) -> List[str]:
        paths = _skill_dirs(root)
        inventory = paths
        return inventory

    def _inspect_sources(self, lock: dict, latest: Dict[str, str], downloads: Path) -> Tuple[dict, dict]:
        source_results, trees = {}, {}
        manifest_names = _manifest_names(self.plugin_root)
        if not manifest_names:
            raise UpdateError("Plugin manifest has no declared skill inventory")
        for name in ALLOWED_REPOSITORIES:
            locked = lock["sources"][name]
            revision = latest[name]
            tree = self._fetch(name, revision, downloads)
            paths = self._inventory(name, tree)
            all_paths = list(paths)
            lock_paths = sorted(locked["skills"])
            manifest_prefix = "matt-" if name == "matt" else "sp-"
            allowed_manifest = sorted(value for value in manifest_names if value.startswith(manifest_prefix))
            if name == "superpowers":
                selected_paths = all_paths
                inventory_changed = sorted(all_paths) != lock_paths
            else:
                selected_paths = _matt_promoted_inventory(tree)
                if any(item not in all_paths for item in selected_paths):
                    raise UpdateError("Matt manifest references a missing promoted skill")
                inventory_changed = selected_paths != lock_paths
            additions = sorted(set(selected_paths) - set(lock_paths))
            removals = sorted(set(lock_paths) - set(selected_paths))
            source_results[name] = {
                "locked_revision": locked["revision"],
                "upstream_revision": revision,
                "update_available": revision != locked["revision"],
                "locked_inventory": lock_paths,
                "upstream_inventory": selected_paths,
                "manifest_inventory": allowed_manifest,
                "inventory_additions": additions,
                "inventory_removals": removals,
                "inventory_changed": inventory_changed,
            }
            trees[name] = tree
        return source_results, trees

    def check(self) -> dict:
        """Read latest main and promoted inventory; no activation or persistent downloads."""
        lock = self._lock()
        latest = {name: self._latest(name) for name in ALLOWED_REPOSITORIES}
        with tempfile.TemporaryDirectory(prefix="freyja-check-", dir=os.environ.get("TMPDIR") or None) as temp:
            results, _ = self._inspect_sources(lock, latest, Path(temp))
        return {
            "current": not any(item["update_available"] or item["inventory_changed"] for item in results.values()),
            "update_available": any(item["update_available"] for item in results.values()),
            "sources": results,
            "upstream_revision": {name: value["upstream_revision"] for name, value in results.items()},
        }

    def _scanner(self) -> Callable[[Path], Any]:
        if self.scanner is not None:
            return self.scanner
        default_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
        hermes_agent = default_home / "hermes-agent"
        explicit = os.environ.get("HERMES_HOME")
        if explicit:
            explicit_root = Path(explicit) / "hermes-agent"
            if explicit_root.is_dir() and str(explicit_root) not in sys.path:
                sys.path.insert(0, str(explicit_root))
        if hermes_agent.is_dir() and str(hermes_agent) not in sys.path:
            sys.path.insert(0, str(hermes_agent))
        if "tools.skills_guard" in sys.modules:
            loaded = sys.modules["tools.skills_guard"]
            if callable(getattr(loaded, "scan_skill", None)):
                return lambda path: _scanner_report(loaded, path)
        candidates = [hermes_agent, Path(__file__).resolve().parents[2] / "hermes-agent"]
        if explicit:
            candidates.insert(0, Path(explicit) / "hermes-agent")
        loaded = None
        for candidate in candidates:
            if (candidate / "tools" / "skills_guard.py").is_file() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            try:
                loaded = importlib.import_module("tools.skills_guard")
                break
            except (ImportError, ModuleNotFoundError, TypeError, AttributeError):
                continue
        if loaded is not None and callable(getattr(loaded, "scan_skill", None)):
            return lambda path: _scanner_report(loaded, path)
        raise UpdateError("Hermes skills_guard scanner unavailable; refusing update")

    def _scan(self, skills_root: Path) -> List[dict]:
        scan = self._scanner()
        reports = []
        for folder in sorted(skills_root.iterdir()):
            if folder.is_symlink() or not folder.is_dir():
                raise UpdateError("Unsafe generated skill directory")
            try:
                report = scan(folder)
            except Exception as exc:
                raise UpdateError("Security scan failed closed for " + folder.name) from exc
            if hasattr(report, "verdict"):
                report = {"verdict": report.verdict, "findings": getattr(report, "findings", [])}
            if not isinstance(report, dict) or report.get("verdict") != "safe":
                raise UpdateError("Security scan was not safe for " + folder.name + ": " + str(report))
            reports.append({"skill": folder.name, "verdict": "safe", "finding_count": len(report.get("findings", []))})
        if not reports:
            raise UpdateError("Generated skill bundle is empty")
        return reports

    def _receipt(self, bundle_root: Path, lock: dict, scan_reports: List[dict]) -> dict:
        _safe_tree(bundle_root)
        files = {}
        for path in sorted(bundle_root.rglob("*")):
            if path.is_file():
                files[path.relative_to(bundle_root).as_posix()] = _digest(path)
        return {
            "receipt_version": 1,
            "verified": True,
            "adapter_version": lock["adapter_version"],
            "lock": lock,
            "source_revisions": {name: item["revision"] for name, item in lock["sources"].items()},
            "inventory": {name: list(item["skills"]) for name, item in lock["sources"].items()},
            "skill_count": sum(len(item["skills"]) for item in lock["sources"].values()),
            "scan": scan_reports,
            "files": files,
        }

    def update(self, apply: bool = False, accept_inventory_changes: bool = False) -> dict:
        """Build a candidate by default; ``apply`` explicitly activates it."""
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._validate_state_root()
        os.chmod(str(self.state_root), 0o700)
        with _FileLock(self.state_root / "update.lock"):
            lock = self._lock()
            latest = {name: self._latest(name) for name in ALLOWED_REPOSITORIES}
            with tempfile.TemporaryDirectory(prefix="freyja-download-", dir=str(self.state_root)) as temp:
                downloads = Path(temp)
                sources, trees = self._inspect_sources(lock, latest, downloads)
                inventory_changes = [name for name, item in sources.items() if item["inventory_changed"]]
                if inventory_changes and not accept_inventory_changes:
                    raise UpdateError("Upstream/plugin inventory changed; pass --accept-inventory-changes explicitly: " + ", ".join(inventory_changes))
                candidate_lock = json.loads(json.dumps(lock))
                for name, tree in trees.items():
                    paths = sources[name]["upstream_inventory"]
                    candidate_lock["sources"][name]["revision"] = latest[name]
                    candidate_lock["sources"][name]["skills"] = paths
                source_root = downloads / "vendor"
                for name, tree in trees.items():
                    destination = source_root / name
                    destination.mkdir(parents=True, mode=0o700)
                    if (tree / "LICENSE").is_file():
                        shutil.copyfile(str(tree / "LICENSE"), str(destination / "LICENSE"))
                    for rel in candidate_lock["sources"][name]["skills"]:
                        src_rel = _safe_relative(rel)
                        source = tree.joinpath(*src_rel.parts)
                        _safe_tree(source)
                        target = destination.joinpath(*src_rel.parts)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(str(source), str(target), symlinks=False)
                output = downloads / "bundle"
                output.mkdir(mode=0o700)
                try:
                    if self.adapter is not None:
                        receipt, validation = self.adapter(source_root, output, candidate_lock)
                    else:
                        from .adapter import build_bundle, validate_bundle
                        receipt = build_bundle(source_root, output, candidate_lock)
                        validation = validate_bundle(output, candidate_lock)
                except ImportError as exc:
                    raise UpdateError("Bundle adapter is not available") from exc
                except Exception as exc:
                    raise UpdateError("Adapter build/critical-anchor validation failed") from exc
                if not isinstance(validation, dict) or validation.get("ok") is not True:
                    raise UpdateError("Adapter validation failed: " + str(validation))
                skills_root = output / "skills"
                if not skills_root.is_dir():
                    raise UpdateError("Adapter returned no generated skills directory")
                actual_skills = {path.name for path in skills_root.iterdir() if path.is_dir() and not path.is_symlink()}
                expected_skills = {
                    ("matt-" if source == "matt" else "sp-") + PurePosixPath(rel).name
                    for source, info in candidate_lock["sources"].items() for rel in info["skills"]
                }
                if actual_skills != expected_skills:
                    raise UpdateError("Adapter output skill inventory differs from accepted lock")
                scan_reports = self._scan(skills_root)
                bundle_receipt = self._receipt(output, candidate_lock, scan_reports)
                bundle_receipt["adapter_receipt"] = receipt
                bundle_receipt["validation"] = validation
                _write_json_atomic(output / "receipt.json", bundle_receipt)
                _safe_tree(output)
                if not apply:
                    staged = self.state_root / "staging" / ("candidate-" + uuid.uuid4().hex)
                    staged.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copytree(str(output), str(staged), symlinks=False)
                    return {"status": "staged", "candidate_root": str(staged), "verified": True,
                            "inventory_changes": inventory_changes, "receipt": bundle_receipt}
                generation = "gen-" + uuid.uuid4().hex
                generations = self.state_root / "generations"
                generations.mkdir(parents=True, exist_ok=True, mode=0o700)
                temp_generation = generations / (".tmp-" + generation)
                shutil.copytree(str(output), str(temp_generation), symlinks=False)
                final_generation = generations / generation
                os.replace(str(temp_generation), str(final_generation))
                generation_info = {"generation": generation, "root": str(final_generation), "lock": candidate_lock,
                                   "receipt": "receipt.json", "receipt_sha256": _digest(final_generation / "receipt.json"),
                                   "verified": True}
                current = self._read_state(allow_missing=True)
                previous = current.get("current") if current else None
                state = {"schema_version": 1, "current": generation_info, "previous": previous}
                _write_json_atomic(self.state_root / "state.json", state)
                result = {"status": "applied", "generation": generation, "active_root": str(final_generation / "skills"),
                        "verified": True, "inventory_changes": inventory_changes, "receipt": bundle_receipt}
                return result

    def _read_state(self, allow_missing: bool = False) -> Optional[dict]:
        path = self.state_root / "state.json"
        self._validate_state_root()
        if not path.exists():
            if allow_missing:
                return None
            raise UpdateError("No active generation")
        if path.is_symlink() or not path.is_file():
            raise UpdateError("Unsafe updater state pointer")
        data = _json(path)
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise UpdateError("Unsupported or corrupt updater state")
        for key in ("current", "previous"):
            item = data.get(key)
            if item is None:
                continue
            if not isinstance(item, dict) or not GENERATION_RE.fullmatch(str(item.get("generation", ""))):
                raise UpdateError("Corrupt generation pointer")
            expected = self.state_root / "generations" / item["generation"]
            if not item.get("lock"):
                receipt_data = _json(expected / "receipt.json")
                item["lock"] = receipt_data.get("lock")
            if item.get("root") != str(expected) or expected.is_symlink() or not expected.is_dir():
                raise UpdateError("Generation root does not match trusted state path")
            receipt = _verify_generation(expected)
            if not DIGEST_RE.fullmatch(str(item.get("receipt_sha256", ""))) or _digest(expected / "receipt.json") != item["receipt_sha256"]:
                raise UpdateError("Generation receipt signature does not match state pointer")
            if item.get("verified") is not True or item.get("lock") != receipt.get("lock"):
                raise UpdateError("Generation is not verified")
        return data

    def status(self) -> dict:
        """Report active generation, or the bundled source tree for legacy installs."""
        result = {"active_root": str(self.plugin_root / "skills"), "root": str(self.plugin_root / "skills"),
                  "lock": None, "verified": False, "generation": None, "source": "bundled"}
        try:
            result["lock"] = self._lock()
        except (UpdateError, OSError):
            result["lock"] = None
        try:
            state = self._read_state(allow_missing=True)
            if state and state.get("current"):
                item = state["current"]
                result.update({"active_root": str(Path(item["root"]) / "skills"), "root": str(Path(item["root"]) / "skills"),
                               "lock": item.get("lock", result["lock"]), "verified": True,
                               "generation": item["generation"], "source": "generation"})
            elif state:
                result["verified"] = False
        except (UpdateError, OSError, KeyError, TypeError):
            result["verified"] = False
        return result

    def rollback(self) -> dict:
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._validate_state_root()
        os.chmod(str(self.state_root), 0o700)
        with _FileLock(self.state_root / "update.lock"):
            state = self._read_state()
            previous = state.get("previous")
            if not previous:
                raise UpdateError("No verified previous generation to restore")
            # _read_state already verified both current and previous; verify target again immediately before switch.
            _verify_generation(Path(previous["root"]))
            new_state = {"schema_version": 1, "current": previous, "previous": state.get("current")}
            _write_json_atomic(self.state_root / "state.json", new_state)
            return {"status": "rolled_back", "generation": previous["generation"],
                    "active_root": str(Path(previous["root"]) / "skills"), "verified": True}


def _extract_tar_safely(archive: Path, destination: Path) -> None:
    base = destination.resolve()
    try:
        with tarfile.open(str(archive), "r:") as tar:
            for member in tar:
                rel = _safe_relative(member.name)
                target = destination.joinpath(*rel.parts)
                if not target.resolve().is_relative_to(base):
                    raise UpdateError("Archive path escapes destination")
                if member.issym() or member.islnk():
                    if rel.parts and rel.parts[0] == "skills":
                        raise UpdateError("Git archive contains a symbolic link in skill content")
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile() or member.type == tarfile.CONTTYPE:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    if source is None:
                        raise UpdateError("Unreadable regular file in Git archive")
                    with source, target.open("xb") as out:
                        shutil.copyfileobj(source, out)
                    target.chmod(0o600)
                else:
                    raise UpdateError("Git archive contains a symlink or special file")
    except (tarfile.TarError, OSError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError("Could not safely extract pinned Git archive") from exc


def _verify_generation(root: Path) -> dict:
    root = Path(root)
    _safe_tree(root)
    receipt_path = root / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise UpdateError("Verified generation is missing its receipt")
    receipt = _json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("receipt_version") != 1 or receipt.get("verified") is not True:
        raise UpdateError("Generation receipt is invalid")
    _validate_lock(receipt.get("lock"))
    if receipt.get("adapter_version") != receipt["lock"].get("adapter_version"):
        raise UpdateError("Generation adapter version does not match its lock")
    if receipt.get("source_revisions") != {name: item["revision"] for name, item in receipt["lock"]["sources"].items()}:
        raise UpdateError("Generation source revisions do not match its lock")
    if receipt.get("inventory") != {name: item["skills"] for name, item in receipt["lock"]["sources"].items()}:
        raise UpdateError("Generation inventory does not match its lock")
    expected = receipt.get("files")
    if not isinstance(expected, dict):
        raise UpdateError("Generation receipt has no file inventory")
    actual_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path != receipt_path}
    if actual_paths != set(expected):
        raise UpdateError("Generation file inventory differs from its receipt")
    for rel, digest in expected.items():
        path = root.joinpath(*_safe_relative(rel).parts)
        if not path.is_file() or _digest(path) != digest:
            raise UpdateError("Generation file hash mismatch: " + rel)
    return receipt
