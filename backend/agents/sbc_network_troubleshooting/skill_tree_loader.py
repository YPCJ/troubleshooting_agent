from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from backend.agents.sbc_network_troubleshooting.tree_schema import (
    FaultTreeDefinition,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILL_PATH = (
    PROJECT_ROOT / "skills" / "sbc_network_troubleshooting" / "SKILL.md"
)
TREE_BLOCK_PATTERN = re.compile(
    r"```yaml\s+sbc-tree\s*\n(?P<yaml>.*?)\n```",
    re.DOTALL,
)


def extract_tree_yaml(markdown: str) -> str:
    matches = list(TREE_BLOCK_PATTERN.finditer(markdown))
    if len(matches) != 1:
        raise ValueError(
            f"SKILL.md must contain exactly one `yaml sbc-tree` block; found {len(matches)}"
        )
    return matches[0].group("yaml")


def load_skill_tree(
    path: Path = DEFAULT_SKILL_PATH,
    *,
    known_tools: set[str],
) -> FaultTreeDefinition:
    markdown = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(extract_tree_yaml(markdown))
    if not isinstance(raw, dict):
        raise ValueError("sbc-tree YAML must be an object")
    try:
        definition = FaultTreeDefinition.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"invalid sbc-tree schema in {path}: {exc}") from exc
    definition.validate_graph(known_tools)
    return definition
