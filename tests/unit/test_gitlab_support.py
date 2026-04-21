from __future__ import annotations

from ppt import __main__ as ppt_main


def test_normalize_gitlab_repo_url_strips_dot_git_and_dash_segment() -> None:
    assert (
        ppt_main.normalize_repo_url("https://gitlab.com/group/subgroup/repo.git")
        == "https://gitlab.com/group/subgroup/repo"
    )
    assert (
        ppt_main.normalize_repo_url("https://gitlab.com/group/repo/-/releases")
        == "https://gitlab.com/group/repo"
    )


def test_owner_repo_name_keeps_full_gitlab_path() -> None:
    assert (
        ppt_main.owner_repo_name("https://gitlab.com/group/subgroup/repo")
        == "group/subgroup/repo"
    )
    assert ppt_main.display_name("https://gitlab.com/group/subgroup/repo") == "repo"


def test_resolve_package_ref_uses_repo_name_as_short_ref() -> None:
    config = [
        ppt_main.PackageConfig(repo="https://gitlab.com/group/subgroup/repo"),
        ppt_main.PackageConfig(repo="https://github.com/other/repo"),
    ]
    assert ppt_main.resolve_package_ref("group/subgroup/repo", config) == "https://gitlab.com/group/subgroup/repo"
    try:
        ppt_main.resolve_package_ref("repo", config)
        raise AssertionError("expected ambiguous package ref")
    except ppt_main.PptError as exc:
        assert "ambiguous" in str(exc)
