from __future__ import annotations

from pathlib import Path
from typing import Any

from llm.config import project_root

try:
    import chardet
except Exception:  # pragma: no cover
    chardet = None

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None


WORKDIR = project_root()


def safe_path(path: str) -> Path:
    resolved = (WORKDIR / path).resolve()
    if not resolved.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path}")
    return resolved


def infer_artifact_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}:
        return "image"
    if suffix in {".md", ".txt", ".doc", ".docx", ".pdf", ".html"}:
        return "document"
    return "data"


def detect_file_encoding(path: str) -> str:
    if chardet is None:
        return "utf-8"
    try:
        raw = safe_path(path).read_bytes()[:50000]
        detected = chardet.detect(raw).get("encoding")
        return str(detected or "utf-8")
    except Exception:
        return "utf-8"


def read_text_smart(path: str, limit: int | None = None) -> str:
    enc_guess = detect_file_encoding(path)
    for enc in [enc_guess, "utf-8", "gbk", "gb2312", "gb18030"]:
        try:
            text = safe_path(path).read_text(encoding=enc)
            lines = text.splitlines()
            if limit and limit < len(lines):
                lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
            return "\n".join(lines)[:50000]
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return f"Error: {exc}"
    return "Error: failed to decode file with supported encodings"


def read_csv(path: str, limit: int | None = None) -> str:
    if pd is None:
        return "Error in read csv files:pandas is not installed"
    nrows = limit or 5
    enc_guess = detect_file_encoding(path)
    for enc in [enc_guess, "utf-8", "gbk", "gb2312", "gb18030"]:
        try:
            df = pd.read_csv(safe_path(path), encoding=enc, nrows=nrows)
            try:
                table = df.to_markdown(index=False)
            except Exception:
                table = df.to_string(index=False)
            return f"读取的csv文件内容为:\n{table}"
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return f"Error in read csv files:{exc}"
    return "Error in read csv files: failed to decode CSV with supported encodings"


def read_file_auto(path: str, limit: int | None = None) -> str:
    suffix = safe_path(path).suffix.lower()
    if suffix == ".csv":
        return read_csv(path, limit)
    return read_text_smart(path, limit)

