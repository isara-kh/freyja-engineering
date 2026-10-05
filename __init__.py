"""Native Hermes entrypoint. No network, upstream hooks or updater at startup."""
from pathlib import Path

from .freyja_engineering.runtime import guidance_for_message, qualified_skills
from .freyja_engineering.updater import BundleManager
from .freyja_engineering.__main__ import main


def active_skills():
    return Path(BundleManager(Path(__file__).resolve().parent).status()['active_root'])


def register(ctx):
    root = Path(__file__).resolve().parent
    for name, path in qualified_skills(active_skills()):
        ctx.register_skill(name, path)
    ctx.register_skill('engineering-guide', root / 'local-skills' / 'engineering-guide' / 'SKILL.md')

    def pre_llm_call(user_message=None, **kwargs):
        hint = guidance_for_message(user_message)
        return {'context': hint} if hint else None

    ctx.register_hook('pre_llm_call', pre_llm_call)
    ctx.register_command('engineering-mode', lambda raw: (
        'Use Freyja engineering by sending "Use Freyja engineering: ' + (raw.strip() or '<your task>') + '". '
        'Load freyja-engineering:engineering-guide. Design approval precedes building; '
        'this command does not execute code or grant external-action permission.'),
        description='Show how to opt in to namespaced engineering workflows')

    def setup(parser):
        parser.add_argument('engineering_command', choices=('check', 'update', 'rollback', 'status'))
        parser.add_argument('--apply', action='store_true', help='Activate after scans and validation')
        parser.add_argument('--accept-inventory-changes', action='store_true')
        parser.add_argument('--state-root', type=Path, default=None)

    def run(args):
        argv = [args.engineering_command, '--plugin-root', str(root)]
        if args.apply:
            argv.append('--apply')
        if args.accept_inventory_changes:
            argv.append('--accept-inventory-changes')
        if args.state_root:
            argv.extend(['--state-root', str(args.state_root)])
        return main(argv)

    ctx.register_cli_command('freyja-engineering', help='Manually check, stage, activate or rollback skill sources', setup_fn=setup, handler_fn=run)
