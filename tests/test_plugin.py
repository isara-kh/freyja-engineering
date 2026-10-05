import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class FakeContext:
    def __init__(self):
        self.skills, self.hooks, self.commands, self.cli = {}, {}, {}, {}

    def register_skill(self, name, path):
        self.skills[name] = path

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = handler

    def register_cli_command(self, name, **kwargs):
        self.cli[name] = kwargs


class PluginTests(unittest.TestCase):
    def plugin(self):
        path = ROOT / '__init__.py'
        if not path.is_file():
            self.fail('Native plugin entrypoint not implemented')
        spec = importlib.util.spec_from_file_location('freyja_plugin_test', path, submodule_search_locations=[str(ROOT)])
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_registration_namespaces_all_upstream_and_separate_guide(self):
        module = self.plugin()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['matt-demo', 'sp-demo']:
                folder = root / name
                folder.mkdir()
                (folder / 'SKILL.md').write_text('---\nname: '+name+'\ndescription: Demo.\n---\nbody')
            ctx = FakeContext()
            with patch.object(module, 'active_skills', return_value=root):
                module.register(ctx)
            self.assertEqual(set(ctx.skills), {'matt-demo', 'sp-demo', 'engineering-guide'})
            self.assertIn('freyja-engineering', ctx.cli)
            self.assertIn('engineering-mode', ctx.commands)

    def test_hook_stays_silent_for_ordinary_turn_and_refreshes_explicit_opt_in(self):
        module = self.plugin()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = FakeContext()
            with patch.object(module, 'active_skills', return_value=root):
                module.register(ctx)
            hook = ctx.hooks['pre_llm_call']
            self.assertIsNone(hook(user_message='What is an ETF?', is_first_turn=True))
            result = hook(user_message='Use Freyja engineering to build an app', is_first_turn=False)
            self.assertIn('engineering-guide', result['context'])
            self.assertLess(len(result['context']), 1800)

    def test_mode_command_returns_guidance_not_side_effecting_build(self):
        module = self.plugin()
        ctx = FakeContext()
        with TemporaryDirectory() as directory:
            with patch.object(module, 'active_skills', return_value=Path(directory)):
                module.register(ctx)
            result = ctx.commands['engineering-mode']('')
            self.assertIn('engineering-guide', result)
            self.assertIn('approval', result.lower())


if __name__ == '__main__':
    unittest.main()
