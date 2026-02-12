#!/usr/bin/env python3
import argparse
import os
import subprocess
from pathlib import Path


def run_git_command(repo_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def get_repo_root(start: Path) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit("Current directory is not inside a git repository.")
    return Path(completed.stdout.strip())


def list_tracked_files(repo_root: Path, pathspecs: list[str]) -> list[Path]:
    output = run_git_command(repo_root, ["ls-files", "-z", "--", *pathspecs])
    entries = [item for item in output.split("\0") if item]
    return [repo_root / item for item in entries]


def get_last_commit_timestamp(repo_root: Path, file_path: Path) -> int | None:
    relative = file_path.relative_to(repo_root)
    output = run_git_command(repo_root, ["log", "-1", "--format=%ct", "--", str(relative)])
    output = output.strip()
    if not output:
        return None
    return int(output)


def restore_mtime(repo_root: Path, file_paths: list[Path], dry_run: bool) -> tuple[int, int]:
    restored = 0
    skipped = 0

    for file_path in file_paths:
        if not file_path.exists() or not file_path.is_file():
            skipped += 1
            continue

        last_commit_time = get_last_commit_timestamp(repo_root, file_path)
        if last_commit_time is None:
            skipped += 1
            continue

        if not dry_run:
            os.utime(file_path, (last_commit_time, last_commit_time))
        restored += 1

    return restored, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively restore file modification times to the timestamp of the "
            "last commit where each file was changed."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories relative to the repository root (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many files would be updated without touching mtimes",
    )
    args = parser.parse_args()

    cwd = Path.cwd()
    repo_root = get_repo_root(cwd)

    restored, skipped = restore_mtime(
        repo_root,
        list_tracked_files(repo_root, args.paths),
        args.dry_run,
    )

    action = "Would restore" if args.dry_run else "Restored"
    print(f"{action} mtimes for {restored} file(s). Skipped {skipped} file(s).")


if __name__ == "__main__":
    main()
