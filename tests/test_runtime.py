import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class RuntimeTests(unittest.TestCase):
    def api(self):
        try:
            from freyja_engineering.runtime import guidance_for_message, qualified_skills
        except ImportError:
            self.fail('Runtime guidance and namespace discovery not implemented')
        return guidance_for_message, qualified_skills

    def test_personal_finance_does_not_activate_engineering(self):
        guidance, _ = self.api()
        self.assertIsNone(guidance('How should I allocate my portfolio?'))

    def test_ordinary_code_question_does_not_force_full_framework(self):
        guidance, _ = self.api()
        self.assertIsNone(guidance('What is a Python list?'))

    def test_explicit_mode_loads_namespaced_policy_not_whole_framework(self):
        guidance, _ = self.api()
        result = guidance('Use Freyja engineering to build a calculator')
        self.assertIn('freyja-engineering:engineering-guide', result)
        self.assertIn('approval', result.lower())
        self.assertLess(len(result), 1800)

    def test_grill_request_maps_to_matt_without_forcing_coding(self):
        guidance, _ = self.api()
        result = guidance('Please grill me about my career plan')
        self.assertIn('freyja-engineering:matt-grill-me', result)
        self.assertNotIn('sp-brainstorming', result)

    def test_unrelated_word_grill_not_a_trigger(self):
        guidance, _ = self.api()
        self.assertIsNone(guidance('How do I clean my grill?'))

    def test_meta_question_about_grill_trigger_does_not_fire(self):
        guidance, _ = self.api()
        self.assertIsNone(guidance('why implement always invoke grill me ?'))

    def test_what_is_grill_question_does_not_fire(self):
        guidance, _ = self.api()
        self.assertIsNone(guidance('what is grill me mode?'))

    def test_explicit_grill_me_about_request_triggers(self):
        guidance, _ = self.api()
        result = guidance('Can you grill me about my CFA plan?')
        self.assertIn('freyja-engineering:matt-grill-me', result)

    def test_bare_leading_grill_me_triggers(self):
        guidance, _ = self.api()
        result = guidance('grill me')
        self.assertIn('freyja-engineering:matt-grill-me', result)

    def test_inventory_qualifies_folders_and_does_not_replace_local_names(self):
        _, discover = self.api()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for slug in ['matt-grill-me', 'sp-test-driven-development']:
                folder = root / slug
                folder.mkdir()
                (folder / 'SKILL.md').write_text('---\nname: '+slug+'\ndescription: test\n---\nbody\n')
            result = discover(root)
            self.assertEqual([name for name, _ in result], ['matt-grill-me', 'sp-test-driven-development'])
            self.assertTrue(all(isinstance(path, Path) for _, path in result))

    def test_symbolic_link_skill_rejected(self):
        _, discover = self.api()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sp-escape').symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(ValueError):
                discover(root)


if __name__ == '__main__':
    unittest.main()
