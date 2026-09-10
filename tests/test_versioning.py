import json
import subprocess
from pathlib import Path

import pytest

from versioning import git_build_info, is_release_tag


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.email', 'version-test@example.invalid')
    git(tmp_path, 'config', 'user.name', 'Version test')
    # Do not inherit host signing or hook configuration in test repositories.
    git(tmp_path, 'config', 'commit.gpgsign', 'false')
    git(tmp_path, 'config', 'tag.gpgsign', 'false')
    git(tmp_path, 'config', 'core.hooksPath', str(tmp_path / 'no-hooks'))
    (tmp_path / 'source.txt').write_text('initial')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'initial')
    return tmp_path


@pytest.mark.parametrize('tag', ['2026.0831.0', '2026.0905.0', '2026.0910.12', '2024.0229.0'])
def test_calver_accepts_padded_month_day(tag):
    assert is_release_tag(tag)


@pytest.mark.parametrize('tag', ['v2026.0905.0', '2026.905.0', '2026.0230.0', '2026.1301.0', '2026.0905.01', '2026.0905.0-dev', '0.1.0'])
def test_calver_rejects_invalid_or_other_version_formats(tag):
    assert not is_release_tag(tag)


@pytest.mark.parametrize('annotated', [False, True])
def test_release_uses_exact_git_tag_without_losing_zeroes(repo, annotated):
    args = ['-a', '-m', 'release'] if annotated else []
    git(repo, 'tag', *args, '2026.0905.0')
    info = git_build_info(repo, '2026.0905.0')
    assert info['version'] == '2026.0905.0'
    assert info['tag'] == info['version']
    assert info['commit'] == git(repo, 'rev-parse', 'HEAD')
    assert info['dirty'] is False
    assert git_build_info(repo)['version'] == '2026.0905.0'


def test_untagged_and_dirty_builds_cannot_masquerade_as_releases(repo):
    assert git_build_info(repo)['version'].startswith('dev+')
    git(repo, 'tag', '2026.0905.0')
    (repo/'source.txt').write_text('modified')
    assert git_build_info(repo)['version'].startswith('2026.0905.0-dev.0+')
    assert git_build_info(repo)['version'].endswith('.dirty')
    with pytest.raises(ValueError, match='未コミット'):
        git_build_info(repo, '2026.0905.0')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'change')
    assert git_build_info(repo)['version'].startswith('2026.0905.0-dev.1+')
    with pytest.raises(ValueError, match='HEAD'):
        git_build_info(repo, '2026.0905.0')


def test_untracked_source_marks_build_dirty(repo):
    git(repo, 'tag', '2026.0905.0')
    (repo/'new.py').write_text('untracked')
    assert git_build_info(repo)['dirty'] is True


def test_multiple_tags_choose_highest_calver_and_ignore_other_tags(repo):
    for tag in ('2026.0905.1', '2026.0905.10', 'v9999.1.0', 'unrelated'):
        git(repo, 'tag', tag)
    assert git_build_info(repo)['version'] == '2026.0905.10'


def test_tag_on_unmerged_branch_is_not_used(repo):
    git(repo, 'switch', '-c', 'other')
    (repo/'source.txt').write_text('other')
    git(repo, 'commit', '-am', 'other')
    git(repo, 'tag', '2026.0905.0')
    git(repo, 'switch', 'main')
    assert git_build_info(repo)['version'].startswith('dev+')


def test_frozen_app_reads_embedded_version_without_git(tmp_path, monkeypatch):
    import app
    (tmp_path/'build_info.json').write_text(json.dumps({'version': '2026.0905.0'}))
    monkeypatch.setattr(app.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(app.sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(app, 'git_build_info', lambda *_: pytest.fail('Bundled app must not call Git'))
    assert app.app_version() == '2026.0905.0'


def test_self_test_rejects_wrong_embedded_version(monkeypatch):
    import app
    monkeypatch.setattr(app, 'app_version', lambda: '2026.0905.0')
    assert app.run_self_test(expected_version='2026.0905.1') == 1
