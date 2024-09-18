"""Utility functions for working with paths in the repository."""

from pathlib import Path

import git


def clone_firmware_repo(repo_parent_path: Path) -> tuple[Path, git.Repo]:
    """Clone the CTS-SAT-1-OBC-Firmware repository."""
    repo = git.Repo.clone_from(
        "https://github.com/CalgaryToSpace/CTS-SAT-1-OBC-Firmware.git",
        to_path=repo_parent_path / "CTS-SAT-1-OBC-Firmware",
        branch="main",
        depth=1,  # Only clone the latest version of the main branch.
    )
    firmware_repo_path = Path(repo_parent_path) / "CTS-SAT-1-OBC-Firmware"

    if not firmware_repo_path.is_dir():
        msg = "Failed to clone CTS-SAT-1-OBC-Firmware repo."
        raise FileNotFoundError(msg)

    return (firmware_repo_path, repo)


def read_text_file(file_path: Path | str) -> str:
    """Read text file as UTF-8 in a cross-platform way."""
    # Note: following encoding arg is very important.
    return Path(file_path).read_text(encoding="utf-8")
