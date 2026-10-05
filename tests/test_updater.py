import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from freyja_engineering.updater import BundleManager, UpdateError


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugin"
        self.state = self.root / "state"
        self.plugin.mkdir()
        (self.plugin / "freyja_engineering").mkdir()
        (self.plugin / "plugin.yaml").write_text(
            "skills:\n  - matt-demo\n  - sp-writing-plans\n"
        )
        self.fixture = self.root / "upstream"
        self.revisions = {}
        self.checkout = {}
        self._make_source("matt", "https://github.com/mattpocock/skills.git", "skills/engineering/demo", "demo")
        self._make_source("superpowers", "https://github.com/obra/superpowers.git", "skills/writing-plans", "writing-plans")
        self.lock = {
            "schema_version": 1,
            "adapter_version": 1,
            "sources": {
                "matt": {
                    "repo": "https://github.com/mattpocock/skills.git",
                    "revision": self.revisions["matt"],
                    "skills": ["skills/engineering/demo"],
                },
                "superpowers": {
                    "repo": "https://github.com/obra/superpowers.git",
                    "revision": self.revisions["superpowers"],
                    "skills": ["skills/writing-plans"],
                },
            },
        }
        (self.plugin / "upstream.lock.json").write_text(json.dumps(self.lock))
        self.manager = self.make_manager()

    def _make_source(self, name, repo, skill_dir, slug):
        checkout = self.fixture / name
        skill = checkout / skill_dir
        skill.mkdir(parents=True)
        (checkout / "LICENSE").write_text("fixture license\n")
        (skill / "SKILL.md").write_text(
            "---\nname: " + slug + "\ndescription: fixture skill.\n---\n"
            "Follow the safe fixture instructions.\n"
        )
        if name == "matt":
            metadata = checkout / ".claude-plugin" / "plugin.json"
            metadata.parent.mkdir(parents=True)
            metadata.write_text(json.dumps({"skills": ["./" + skill_dir]}))
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
        subprocess.run(["git", "-C", str(checkout), "commit", "-qm", "fixture"], check=True)
        revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        self.revisions[name] = revision
        self.checkout[name] = checkout

    def make_manager(self, *, scanner="default", revisions=None, checkouts=None):
        def fixture_adapter(vendor, output, lock):
            skills = output / "skills"
            skills.mkdir()
            for source_name, source_info in lock["sources"].items():
                prefix = "matt-" if source_name == "matt" else "sp-"
                for rel in source_info["skills"]:
                    slug = prefix + Path(rel).name
                    folder = skills / slug
                    folder.mkdir()
                    (folder / "SKILL.md").write_text(
                        "---\nname: " + slug + "\ndescription: fixture.\n---\nSafe fixture.\n"
                    )
            return {"skill_count": sum(len(item["skills"]) for item in lock["sources"].values())}, {"ok": True}

        return BundleManager(
            self.plugin,
            self.state,
            revision_resolver=lambda source: (revisions or self.revisions)[source],
            fetcher=lambda source, revision: (checkouts or self.checkout)[source],
            scanner=(lambda path: {"verdict": "safe", "findings": []}) if scanner == "default" else scanner,
            adapter=fixture_adapter,
        )

    def test_check_is_read_only_and_reports_remote_revision(self):
        result = self.manager.check()
        self.assertEqual(result["sources"]["matt"]["upstream_revision"], self.revisions["matt"])
        self.assertFalse(result["update_available"])
        self.assertFalse(self.state.exists())

    def test_public_manager_rejects_unsupported_source_url_before_network(self):
        lock = json.loads((self.plugin / "upstream.lock.json").read_text())
        lock["sources"]["matt"]["repo"] = "https://attacker.invalid/payload.git"
        (self.plugin / "upstream.lock.json").write_text(json.dumps(lock))
        with self.assertRaises(UpdateError):
            self.manager.check()

    def test_cli_status_reports_bundled_root_without_network(self):
        result = subprocess.run(
            [sys.executable, "-m", "freyja_engineering", "status", "--plugin-root", str(self.plugin),
             "--state-root", str(self.state)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertEqual(status["source"], "bundled")
        self.assertFalse(self.state.exists())

        result = self.manager.update()
        self.assertEqual(result["status"], "staged")
        self.assertTrue(Path(result["candidate_root"]).is_dir())
        self.assertFalse((self.state / "state.json").exists())

    def test_apply_activates_atomic_verified_generation_and_rollback_restores_previous(self):
        first = self.manager.update(apply=True)
        current = self.manager.status()
        self.assertEqual(current["active_root"], first["active_root"])
        self.assertTrue(current["verified"])
        changed = self.root / "changed-matt"
        subprocess.run(["git", "clone", "-q", str(self.checkout["matt"]), str(changed)], check=True)
        subprocess.run(["git", "-C", str(changed), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(changed), "config", "user.name", "Fixture"], check=True)
        (changed / "skills/engineering/demo/SKILL.md").write_text(
            "---\nname: demo\ndescription: revised.\n---\nRevised safe instructions.\n"
        )
        subprocess.run(["git", "-C", str(changed), "commit", "-qam", "change"], check=True)
        second_revision = subprocess.check_output(["git", "-C", str(changed), "rev-parse", "HEAD"], text=True).strip()
        revisions = dict(self.revisions, matt=second_revision)
        checkouts = dict(self.checkout, matt=changed)
        changed_manager = self.make_manager(revisions=revisions, checkouts=checkouts)
        second = changed_manager.update(apply=True)
        self.assertNotEqual(first["generation"], second["generation"])
        rolled = changed_manager.rollback()
        self.assertEqual(rolled["generation"], first["generation"])
        self.assertTrue(changed_manager.status()["verified"])

    def test_caution_or_dangerous_scan_blocks_apply(self):
        for verdict in ("caution", "dangerous"):
            manager = self.make_manager(scanner=lambda path, verdict=verdict: {"verdict": verdict, "findings": [verdict]})
            with self.subTest(verdict=verdict), self.assertRaises(UpdateError):
                manager.update(apply=True)
        self.assertFalse((self.state / "state.json").exists())

    def test_injected_scanner_receipt_covers_generated_fixture(self):
        reports = self.manager.update()
        self.assertTrue(reports["verified"])
        self.assertEqual(reports["receipt"]["scan"][0]["verdict"], "safe")
        self.assertGreaterEqual(len(reports["receipt"]["scan"]), 2)

    def test_inventory_change_requires_explicit_acceptance(self):
        changed = self.root / "changed-sp"
        subprocess.run(["git", "clone", "-q", str(self.checkout["superpowers"]), str(changed)], check=True)
        extra = changed / "skills/new-skill"
        extra.mkdir(parents=True)
        (extra / "SKILL.md").write_text("---\nname: new-skill\ndescription: new.\n---\nNew.\n")
        subprocess.run(["git", "-C", str(changed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(changed), "commit", "-qm", "inventory"], check=True)
        revision = subprocess.check_output(["git", "-C", str(changed), "rev-parse", "HEAD"], text=True).strip()
        manager = self.make_manager(revisions=dict(self.revisions, superpowers=revision), checkouts=dict(self.checkout, superpowers=changed))
        with self.assertRaises(UpdateError):
            manager.update(apply=True)
        accepted = manager.update(apply=True, accept_inventory_changes=True)
        self.assertTrue(accepted["verified"])

    def test_check_reports_full_promoted_matt_inventory_and_additions(self):
        changed = self.root / "changed-matt"
        subprocess.run(["git", "clone", "-q", str(self.checkout["matt"]), str(changed)], check=True)
        extra = changed / "skills/engineering/new-skill"
        extra.mkdir(parents=True)
        (extra / "SKILL.md").write_text("---\nname: new-skill\ndescription: new.\n---\nNew.\n")
        metadata = changed / ".claude-plugin/plugin.json"
        metadata.write_text(json.dumps({"skills": ["./skills/engineering/demo", "./skills/engineering/new-skill"]}))
        subprocess.run(["git", "-C", str(changed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(changed), "commit", "-qm", "promote"], check=True)
        revision = subprocess.check_output(["git", "-C", str(changed), "rev-parse", "HEAD"], text=True).strip()
        manager = self.make_manager(revisions=dict(self.revisions, matt=revision), checkouts=dict(self.checkout, matt=changed))
        result = manager.check()["sources"]["matt"]
        self.assertEqual(result["upstream_inventory"], ["skills/engineering/demo", "skills/engineering/new-skill"])
        self.assertEqual(result["inventory_additions"], ["skills/engineering/new-skill"])
        self.assertEqual(result["inventory_removals"], [])
        self.assertTrue(result["inventory_changed"])

    def test_apply_accepts_inventory_then_check_uses_active_generation_lock(self):
        changed = self.root / "changed-matt"
        subprocess.run(["git", "clone", "-q", str(self.checkout["matt"]), str(changed)], check=True)
        extra = changed / "skills/engineering/new-skill"
        extra.mkdir(parents=True)
        (extra / "SKILL.md").write_text("---\nname: new-skill\ndescription: new.\n---\nNew.\n")
        metadata = changed / ".claude-plugin/plugin.json"
        metadata.write_text(json.dumps({"skills": ["./skills/engineering/demo", "./skills/engineering/new-skill"]}))
        subprocess.run(["git", "-C", str(changed), "add", "."], check=True)
        subprocess.run(["git", "-C", str(changed), "commit", "-qm", "promote"], check=True)
        revision = subprocess.check_output(["git", "-C", str(changed), "rev-parse", "HEAD"], text=True).strip()
        manager = self.make_manager(revisions=dict(self.revisions, matt=revision), checkouts=dict(self.checkout, matt=changed))
        with self.assertRaises(UpdateError):
            manager.update(apply=True)
        manager.update(apply=True, accept_inventory_changes=True)
        result = manager.check()
        self.assertTrue(result["current"])
        self.assertFalse(result["sources"]["matt"]["inventory_changed"])
        self.assertEqual(result["sources"]["matt"]["locked_inventory"], ["skills/engineering/demo", "skills/engineering/new-skill"])

    def test_check_uses_configured_tmpdir(self):
        configured_tmp = self.root / "scratch"
        configured_tmp.mkdir()
        with mock.patch.dict(os.environ, {"TMPDIR": str(configured_tmp)}):
            self.manager.check()
        self.assertEqual(list(configured_tmp.iterdir()), [])
        self.assertFalse(self.state.exists())

    def test_lock_rejects_adapter_version_drift(self):
        lock = json.loads((self.plugin / "upstream.lock.json").read_text())
        lock["adapter_version"] = 999
        (self.plugin / "upstream.lock.json").write_text(json.dumps(lock))
        with self.assertRaises(UpdateError):
            self.manager.check()

    def test_fetch_tolerates_unrelated_root_agents_symlink(self):
        changed = self.root / "agents-link"
        subprocess.run(["git", "clone", "-q", str(self.checkout["matt"]), str(changed)], check=True)
        (changed / "AGENTS.md").symlink_to("skills/engineering/demo/SKILL.md")
        subprocess.run(["git", "-C", str(changed), "add", "AGENTS.md"], check=True)
        subprocess.run(["git", "-C", str(changed), "commit", "-qm", "unrelated symlink"], check=True)
        revision = subprocess.check_output(["git", "-C", str(changed), "rev-parse", "HEAD"], text=True).strip()
        manager = self.make_manager(revisions=dict(self.revisions, matt=revision), checkouts=dict(self.checkout, matt=changed))
        downloads = self.root / "downloads"
        downloads.mkdir()
        self.assertTrue(manager._fetch("matt", revision, downloads).is_dir())

    def test_symlink_in_download_is_rejected(self):
        link = self.checkout["matt"] / "skills/engineering/demo/escape"
        link.symlink_to(self.checkout["matt"] / "LICENSE")
        with self.assertRaises(UpdateError):
            self.manager.update(apply=True)

    def test_rollback_rejects_corrupt_pointer_without_destroying_state(self):
        self.manager.update(apply=True)
        state_file = self.state / "state.json"
        original = state_file.read_text()
        state_file.write_text("{corrupt")
        with self.assertRaises(UpdateError):
            self.manager.rollback()
        self.assertEqual(state_file.read_text(), "{corrupt")
        self.assertNotEqual(original, state_file.read_text())

    def test_previous_generation_corruption_prevents_unsafe_rollback(self):
        first = self.manager.update(apply=True)
        changed = self.root / "changed"
        subprocess.run(["git", "clone", "-q", str(self.checkout["matt"]), str(changed)], check=True)
        subprocess.run(["git", "-C", str(changed), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(changed), "config", "user.name", "Fixture"], check=True)
        (changed / "skills/engineering/demo/SKILL.md").write_text("---\nname: demo\ndescription: changed.\n---\nChanged.\n")
        subprocess.run(["git", "-C", str(changed), "commit", "-qam", "change"], check=True)
        rev = subprocess.check_output(["git", "-C", str(changed), "rev-parse", "HEAD"], text=True).strip()
        second_mgr = self.make_manager(revisions=dict(self.revisions, matt=rev), checkouts=dict(self.checkout, matt=changed))
        second_mgr.update(apply=True)
        old_skill = Path(first["active_root"]) / "matt-demo/SKILL.md"
        old_skill.write_text("tampered\n")
        with self.assertRaises(UpdateError):
            second_mgr.rollback()
        self.assertTrue(second_mgr.status()["verified"] is False)

    def test_two_simultaneous_applies_serialize_and_keep_valid_state(self):
        results, errors = [], []
        barrier = threading.Barrier(3)
        def apply():
            barrier.wait()
            try:
                results.append(self.manager.update(apply=True))
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=apply) for _ in range(2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(20)
        self.assertFalse(errors, errors)
        self.assertEqual(len(results), 2)
        self.assertTrue(self.manager.status()["verified"])


if __name__ == "__main__":
    unittest.main()
