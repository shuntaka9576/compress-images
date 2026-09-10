"""CalVer display versions sourced from Git, with explicit development builds."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import subprocess


CALVER = re.compile(r"([0-9]{4})\.([0-9]{2})([0-9]{2})\.(0|[1-9][0-9]*)\Z")


def is_release_tag(tag: str) -> bool:
    match = CALVER.fullmatch(tag)
    if not match:
        return False
    try:
        date(*(int(part) for part in match.groups()[:3]))
    except ValueError:
        return False
    return True


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE,
        encoding="utf-8", timeout=30,
    ).strip()


def git_build_info(root: Path, release_tag: str | None = None) -> dict[str, object]:
    """Release mode requires a real, clean tag checkout; it never invents a tag."""
    if release_tag is not None and not is_release_tag(release_tag):
        raise ValueError("リリースタグは YYYY.MMDD.連番 形式で指定してください。")
    commit = _git(root, "rev-parse", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=normal"))
    exact_tags = [tag for tag in _git(root, "tag", "--points-at", "HEAD", "--sort=-version:refname").splitlines()
                  if is_release_tag(tag)]
    if release_tag is not None:
        if release_tag not in exact_tags:
            raise ValueError("指定したリリースタグは現在のHEADを指していません。")
        if dirty:
            raise ValueError("リリースビルドには未コミットの変更がないチェックアウトが必要です。")
        tag = release_tag
        version = tag
    elif exact_tags and not dirty:
        tag = exact_tags[0]
        version = tag
    else:
        tag = next((tag for tag in _git(root, "tag", "--merged", "HEAD", "--sort=-version:refname").splitlines()
                    if is_release_tag(tag)), None)
        if tag:
            distance = _git(root, "rev-list", "--count", f"{tag}..HEAD")
            version = f"{tag}-dev.{distance}+{commit[:7]}"
        else:
            version = f"dev+{commit[:7]}"
        if dirty:
            version += ".dirty"
    return {"version": version, "commit": commit, "tag": tag, "dirty": dirty}
