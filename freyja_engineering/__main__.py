"""Manual Freyja Engineering bundle maintenance CLI; never runs on plugin startup."""
import argparse
import json
import sys
from pathlib import Path

from .updater import BundleManager, UpdateError


def _parser():
    parser = argparse.ArgumentParser(prog="python -m freyja_engineering")
    parser.add_argument("command", choices=("check", "update", "rollback", "status"))
    parser.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-root", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="activate a verified staged update")
    parser.add_argument("--accept-inventory-changes", action="store_true",
                        help="explicitly accept upstream/plugin inventory changes")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    manager = BundleManager(args.plugin_root, args.state_root)
    try:
        if args.command == "check":
            result = manager.check()
        elif args.command == "update":
            result = manager.update(apply=args.apply, accept_inventory_changes=args.accept_inventory_changes)
        elif args.command == "rollback":
            result = manager.rollback()
        else:
            result = manager.status()
    except UpdateError as exc:
        print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
