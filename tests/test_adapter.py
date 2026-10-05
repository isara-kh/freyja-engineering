import json
import shutil
import tempfile
import unittest
from pathlib import Path

from freyja_engineering.adapter import (
    AdapterError,
    build_bundle,
    validate_adapter_signatures,
    validate_bundle,
)


class AdapterTests(unittest.TestCase):
    def make_fixture(self, root: Path):
        vendor = root / "vendor"
        output = root / "generated"
        matt = vendor / "matt" / "skills" / "engineering" / "demo"
        superpower = vendor / "superpowers" / "skills" / "writing-plans"
        matt.mkdir(parents=True)
        superpower.mkdir(parents=True)
        (vendor / "matt" / "LICENSE").write_text("matt license\n")
        (vendor / "superpowers" / "LICENSE").write_text("sp license\n")
        (matt / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Demo.\n---\n"
            "Read [helper](../helper/SKILL.md). Call the Skill tool with `helper`.\n"
        )
        (matt.parent / "helper").mkdir()
        (matt.parent / "helper" / "SKILL.md").write_text(
            "---\nname: helper\ndescription: Helper.\n---\nHelper.\n"
        )
        (matt / "guide.md").write_text("Supporting file.\n")
        (matt / "data.env.example").write_text("TOKEN=example-only\n")
        (superpower / "SKILL.md").write_text(
            "---\nname: writing-plans\ndescription: Plans.\n---\nPlan safely.\n"
        )
        lock = {
            "schema_version": 1,
            "adapter_version": 1,
            "sources": {
                "matt": {
                    "repo": "https://github.com/mattpocock/skills.git",
                    "revision": "1" * 40,
                    "skills": ["skills/engineering/demo", "skills/engineering/helper"],
                },
                "superpowers": {
                    "repo": "https://github.com/obra/superpowers.git",
                    "revision": "2" * 40,
                    "skills": ["skills/writing-plans"],
                },
            },
        }
        fixture_signatures = {
            "adapter_version": 1,
            "signatures": {
                "matt:skills/engineering/demo": {
                    "anchor": "Call the Skill tool",
                    "count": 1,
                    "sha256": "d7646eecbec1411623846f5530f4c5060ee8ee601825c1e9b262d8324af3a9f7",
                }
            },
        }
        return vendor, output, lock, fixture_signatures

    def test_build_namespaces_frontmatter_references_and_preserves_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            vendor, output, lock, signatures = self.make_fixture(Path(td))
            receipt = build_bundle(vendor, output, lock, signature_policy=signatures)
            skill = (output / "skills" / "matt-demo" / "SKILL.md").read_text()
            self.assertIn("name: matt-demo", skill)
            self.assertIn("freyja-engineering:matt-helper", skill)
            self.assertIn("../matt-helper/SKILL.md", skill)
            self.assertIn("Hermes", skill)
            self.assertTrue((output / "skills" / "matt-demo" / "guide.md").is_file())
            self.assertEqual((output / "vendor" / "matt" / "LICENSE").read_text(), "matt license\n")
            self.assertEqual(receipt["skill_count"], 3)
            self.assertTrue(validate_bundle(output, lock)["ok"])

    def test_build_refuses_nonempty_output_and_unsafe_vendor_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            vendor, output, lock, signatures = self.make_fixture(Path(td))
            output.mkdir()
            (output / "keep").write_text("untouched")
            with self.assertRaises(AdapterError):
                build_bundle(vendor, output, lock, signature_policy=signatures)
            self.assertEqual((output / "keep").read_text(), "untouched")
            (output / "keep").unlink()
            output.rmdir()
            (vendor / "matt" / "skills" / "engineering" / "demo" / "link.md").symlink_to(
                vendor / "matt" / "LICENSE"
            )
            with self.assertRaises(AdapterError):
                build_bundle(vendor, output, lock)

    def test_critical_anchor_signature_change_fails_closed(self):
        project = Path(__file__).resolve().parents[1]
        lock = json.loads((project / "upstream.lock.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            vendor = Path(td) / "vendor"
            output = Path(td) / "generated"
            shutil.copytree(project / "vendor", vendor)
            skill = vendor / "matt" / "skills" / "engineering" / "improve-codebase-architecture" / "SKILL.md"
            skill.write_text(skill.read_text().replace("Mermaid via CDN", "local diagrams"))
            with self.assertRaises(AdapterError) as raised:
                build_bundle(vendor, output, lock)
            self.assertIn("signature conflict", str(raised.exception).lower())

    def test_validator_reports_missing_and_unexpected_skill_directories(self):
        with tempfile.TemporaryDirectory() as td:
            vendor, output, lock, signatures = self.make_fixture(Path(td))
            build_bundle(vendor, output, lock, signature_policy=signatures)
            (output / "skills" / "matt-helper").rename(output / "skills" / "matt-helper-moved")
            result = validate_bundle(output, lock)
            self.assertFalse(result["ok"])
            self.assertTrue(result["findings"])

    def test_real_bundle_has_all_sources_and_safe_known_examples(self):
        project = Path(__file__).resolve().parents[1]
        lock = json.loads((project / "upstream.lock.json").read_text())
        result = validate_bundle(project / "skills", lock)
        self.assertTrue(result["ok"], result["findings"])
        self.assertEqual(result["skill_count"], 42)
        arch = (project / "skills" / "matt-improve-codebase-architecture" / "SKILL.md").read_text()
        self.assertIn("never fetch Tailwind or Mermaid from a remote CDN", arch)
        self.assertIn("Escape every untrusted", arch)
        debug = (project / "skills/sp-systematic-debugging/SKILL.md").read_text()
        self.assertNotIn('echo "=== Secrets available in workflow: ==="', debug)
        self.assertIn("names only", debug)

    def test_signature_checker_detects_known_semantic_anchor_modification(self):
        project = Path(__file__).resolve().parents[1]
        lock = json.loads((project / "upstream.lock.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            copied_vendor = Path(td) / "vendor"
            shutil.copytree(project / "vendor", copied_vendor)
            target = copied_vendor / "matt/skills/engineering/improve-codebase-architecture/SKILL.md"
            text = target.read_text()
            self.assertIn("Mermaid via CDN", text)
            baseline = validate_adapter_signatures(copied_vendor, lock)
            self.assertTrue(baseline["ok"], baseline["findings"])
            target.write_text(text.replace("Mermaid via CDN", "local diagrams"))
            result = validate_adapter_signatures(copied_vendor, lock)
            self.assertFalse(result["ok"])
            self.assertTrue(result["findings"])

    def test_signature_checker_detects_upstream_anchor_drift(self):
        project = Path(__file__).resolve().parents[1]
        lock = json.loads((project / "upstream.lock.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            copied_vendor = Path(td) / "vendor"
            shutil.copytree(project / "vendor", copied_vendor)
            result = validate_adapter_signatures(copied_vendor, lock)
            self.assertTrue(result["ok"], result["findings"])
            target = copied_vendor / "matt/skills/engineering/improve-codebase-architecture/SKILL.md"
            target.write_text(target.read_text().replace("Mermaid via CDN", "local diagrams"))
            drift = validate_adapter_signatures(copied_vendor, lock)
            self.assertFalse(drift["ok"])
            self.assertTrue(drift["findings"])

    def test_build_sanitizes_architecture_sidecars_and_rewrites_namespaces_and_tool_map(self):
        project = Path(__file__).resolve().parents[1]
        lock = json.loads((project / "upstream.lock.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            vendor = Path(td) / "vendor"
            output = Path(td) / "generated"
            shutil.copytree(project / "vendor", vendor)
            build_bundle(vendor, output, lock)
            arch = output / "skills/matt-improve-codebase-architecture/HTML-REPORT.md"
            text = arch.read_text()
            self.assertNotIn("<script", text.lower())
            self.assertNotIn("cdn.jsdelivr.net", text)
            self.assertNotIn("securityLevel: \\\"loose\\\"", text)
            self.assertIn("escaped plain text", text)
            self.assertIn("## Candidate card", text)
            refs = (output / "skills/sp-using-superpowers/references/hermes-tools.md").read_text()
            self.assertNotIn("toolsets=[...], role=", refs)
            self.assertNotIn("terminal` with `find`", refs)
            self.assertNotIn("| Task tracking | `todo` tool", refs)
            self.assertIn("delegate_task({goal: ..., context: ...})", refs)
            self.assertIn("search_files", refs)
            self.assertIn("todo_list", refs)
            self.assertNotIn("superpowers:finishing-a-development-branch", refs)
            self.assertIn("freyja-engineering:sp-brainstorming", refs)
            result = validate_bundle(output, lock)
            self.assertTrue(result["ok"], result["findings"])

    def test_build_makes_cleanup_require_receipt_and_exact_scoped_authorization(self):
        project = Path(__file__).resolve().parents[1]
        lock = json.loads((project / "upstream.lock.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            vendor = Path(td) / "vendor"
            output = Path(td) / "generated"
            shutil.copytree(project / "vendor", vendor)
            build_bundle(vendor, output, lock)
            text = (output / "skills/sp-finishing-a-development-branch/SKILL.md").read_text()
            self.assertIn("creation receipt", text.lower())
            self.assertIn("explicit scoped authorization", text.lower())
            self.assertIn("exact path", text.lower())

    def test_build_makes_wizard_persistence_interactive_and_private(self):
        project = Path(__file__).resolve().parents[1]
        lock = json.loads((project / "upstream.lock.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            vendor = Path(td) / "vendor"
            output = Path(td) / "generated"
            shutil.copytree(project / "vendor", vendor)
            build_bundle(vendor, output, lock)
            template = (output / "skills/matt-wizard/template.sh").read_text()
            self.assertIn("explicit confirmation", template.lower())
            self.assertIn("umask 077", template)
            self.assertIn("[[ -t 0 ]]", template)
            self.assertIn("confirm", template)
            self.assertIn("write_env", template)
            self.assertIn("set_secret", template)


if __name__ == "__main__":
    unittest.main()
