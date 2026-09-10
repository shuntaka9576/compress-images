"""Generate immutable version metadata before invoking PyInstaller."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from versioning import git_build_info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag", help="Require this exact CalVer tag on a clean HEAD")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "build_info.json")
    args = parser.parse_args()
    try:
        info = git_build_info(ROOT, args.release_tag)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        parser.exit(1, f"バージョン情報を作成できませんでした: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Build version: {info['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
