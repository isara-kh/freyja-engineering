"""Offline integration check using the real Hermes PluginManager in a fresh home."""
import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    scratch = Path(os.environ.get('TMPDIR', str(Path.home() / '.hermes/cache/scratch')))
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='freyja-native-check-', dir=str(scratch)) as directory:
        home = Path(directory)
        destination = home / 'plugins/freyja-engineering'
        shutil.copytree(ROOT, destination, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
        (home / 'config.yaml').write_text('plugins:\n  enabled: [freyja-engineering]\n', encoding='utf-8')
        os.environ['HERMES_HOME'] = str(home)
        from hermes_cli.plugins import PluginManager
        manager = PluginManager()
        manager.discover_and_load()
        skills = manager.list_plugin_skills('freyja-engineering')
        expected = json.loads((ROOT / 'upstream.lock.json').read_text())
        slugs = {'matt-' + Path(path).name for path in expected['sources']['matt']['skills']}
        slugs |= {'sp-' + Path(path).name for path in expected['sources']['superpowers']['skills']}
        slugs.add('engineering-guide')
        actual = {name.split(':')[-1] for name in skills}
        assert actual == slugs, (len(actual), sorted(slugs - actual), skills)
        for slug in sorted(slugs):
            path = manager.find_plugin_skill('freyja-engineering:' + slug)
            assert path is not None and path.is_file(), slug
        print(json.dumps({'native_registered': len(actual), 'upstream_skills': len(actual)-1, 'local_guides': 1,
                          'all_namespaced_paths_exist': True, 'isolated_profile': True}, indent=2))


if __name__ == '__main__':
    main()
