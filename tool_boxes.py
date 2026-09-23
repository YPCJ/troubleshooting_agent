from pathlib import Path
import threading


class TodoManager:
    def __init__(self):
        self._local = threading.local()

    @property
    def items(self) -> list:
        return getattr(self._local, "items", [])

    @items.setter
    def items(self, value: list) -> None:
        self._local.items = value

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


def find_project_root(start: Path, marker: str = ".env") -> Path:
    for p in [start, *start.parents]:
        if (p / marker).exists():
            return p
    return start


def resolve_skills_dir(module_file: str | Path, workdir: Path, project_root: Path) -> Path:
    candidates = [
        project_root / "skills",
        workdir / "skills",
    ]
    for p in candidates:
        if p.exists():
            return p
    return project_root / "skills"
