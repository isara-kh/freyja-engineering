"""Small, explicit routing hints; never global engineering policy injection."""
import re
from pathlib import Path
from typing import List, Optional, Tuple


NAMESPACE = 'freyja-engineering'


def guidance_for_message(message: str) -> Optional[str]:
    """Recognize explicit opt-in, not inferred intent from arbitrary private data."""
    if not isinstance(message, str):
        return None
    lowered = message.lower()
    if re.search(r'\bgrill[ -]me\b', lowered):
        return ('The user requested grilling. Load skill_view(name="freyja-engineering:matt-grill-me"). '
                'Use it for this decision only; do not start a coding pipeline or take action without approval.')
    if re.search(r'\b(?:use|using|enable|start) freyja[ -]engineering\b', lowered) or lowered.startswith('/engineering-mode'):
        return ('The user explicitly requested the Freyja engineering workflow. '
                'Load skill_view(name="freyja-engineering:engineering-guide") and the appropriate qualified skill. '
                'Plan/design approval precedes building; preserve scope and consent. '
                'This reminder is guidance, not permission for account access or external/destructive actions.')
    return None


def qualified_skills(root: Path) -> List[Tuple[str, Path]]:
    """Inventory only immediate skill folders; reject symlinks and invalid names."""
    root = Path(root)
    if root.is_symlink():
        raise ValueError('Skill root must not be a symbolic link')
    if not root.is_dir():
        raise ValueError('Skill root is missing')
    result = []
    for folder in sorted(root.iterdir()):
        if folder.is_symlink():
            raise ValueError('Symbolic link in skill inventory: ' + folder.name)
        if not folder.is_dir():
            continue
        path = folder / 'SKILL.md'
        if path.is_symlink():
            raise ValueError('Linked skill document: ' + folder.name)
        if path.is_file():
            if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', folder.name):
                raise ValueError('Invalid skill slug: ' + folder.name)
            result.append((folder.name, path))
    return result
