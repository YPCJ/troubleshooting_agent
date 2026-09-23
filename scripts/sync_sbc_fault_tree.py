from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agents.sbc_network_troubleshooting.config import load_runtime_tree
from backend.agents.sbc_network_troubleshooting.mermaid_renderer import (
    render_mermaid,
    replace_mermaid,
)
from backend.agents.sbc_network_troubleshooting.skill_tree_loader import (
    DEFAULT_SKILL_PATH,
)


def synchronize(*, write: bool) -> bool:
    definition = load_runtime_tree()
    markdown = DEFAULT_SKILL_PATH.read_text(encoding="utf-8")
    synchronized = replace_mermaid(markdown, render_mermaid(definition))
    is_current = synchronized == markdown
    if write and not is_current:
        DEFAULT_SKILL_PATH.write_text(synchronized, encoding="utf-8")
        is_current = True

    mode = "updated" if write else "checked"
    print(
        f"{mode}: {len(definition.nodes)} nodes, "
        f"{len(definition.conclusions())} conclusions"
    )
    if not is_current:
        print(
            "Mermaid is out of sync. Run "
            "`.venv/bin/python scripts/sync_sbc_fault_tree.py --write`.",
            file=sys.stderr,
        )
    return is_current


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate SBC fault-tree YAML and synchronize its Mermaid view."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    return 0 if synchronize(write=args.write) else 1


if __name__ == "__main__":
    raise SystemExit(main())
