"""Disposable artifact smoke test. Tests real code, not model behavior."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix='freyja-coding-smoke-', dir=os.environ.get('TMPDIR')) as directory:
        root = Path(directory)
        (root / 'test_calculator.py').write_text(
            'import unittest\nfrom calculator import add\n'
            'class Tests(unittest.TestCase):\n'
            ' def test_add(self):\n  self.assertEqual(add(2, 3), 5)\n'
            ' def test_negative(self):\n  self.assertEqual(add(-2, 3), 1)\n', encoding='utf-8')
        (root / 'calculator.py').write_text('def add(a, b):\n    raise NotImplementedError("not implemented")\n')
        command = [sys.executable, '-m', 'unittest', 'discover', '-v']
        red = subprocess.run(command, cwd=root, capture_output=True, text=True)
        assert red.returncode != 0 and 'NotImplementedError' in red.stderr, red.stderr
        print('RED: real tests fail for unimplemented addition.')
        (root / 'calculator.py').write_text('def add(a, b):\n    return a + b\n')
        green = subprocess.run(command, cwd=root, capture_output=True, text=True)
        assert green.returncode == 0, green.stderr
        print(green.stderr)
        print(json.dumps({'artifact_smoke': 'passed', 'red_exit': red.returncode,
                          'green_exit': green.returncode, 'model_behavior_eval': False}))


if __name__ == '__main__':
    main()
