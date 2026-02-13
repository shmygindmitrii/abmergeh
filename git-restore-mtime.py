#!/usr/bin/env python3
import argparse
import os
import subprocess
import time
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


def get_last_commit_timestamps(
    repo_root: Path,
    pathspecs: list[str],
) -> dict[Path, int]:
    output = run_git_command(
        repo_root,
        ["log", "--format=__COMMIT__%ct", "--name-only", "--", *pathspecs],
    )

    last_timestamps: dict[Path, int] = {}
    current_timestamp: int | None = None

    for line in output.splitlines():
        if not line:
            continue

        if line.startswith("__COMMIT__"):
            current_timestamp = int(line.removeprefix("__COMMIT__"))
            continue

        if current_timestamp is None:
            continue

        relative_path = Path(line)
        if relative_path not in last_timestamps:
            last_timestamps[relative_path] = current_timestamp

    return last_timestamps


class ProgressTracker:
    def __init__(self, total: int) -> None:
        self.total = total
        self.enabled = total > 100
        self.start_monotonic = time.monotonic()
        self.current_percent = 0

        if self.enabled:
            print(f"Processing {self.total} file(s)...")

    def update(self, processed: int) -> None:
        if not self.enabled:
            return

        target_percent = int((processed / self.total) * 100)
        while self.current_percent < target_percent:
            self.current_percent += 1
            elapsed = time.monotonic() - self.start_monotonic
            per_item = elapsed / processed if processed else 0.0
            remaining = max(self.total - processed, 0)
            eta_seconds = int(per_item * remaining)
            print(
                f"Progress: {self.current_percent}% "
                f"({processed}/{self.total}), ETA: {eta_seconds}s"
            )


def restore_mtime(
    repo_root: Path,
    file_paths: list[Path],
    last_commit_timestamps: dict[Path, int],
    dry_run: bool,
) -> tuple[int, int]:
    restored = 0
    skipped = 0

    progress = ProgressTracker(len(file_paths))

    for index, file_path in enumerate(file_paths, start=1):
        if not file_path.exists() or not file_path.is_file():
            skipped += 1
            progress.update(index)
            continue

        relative_path = file_path.relative_to(repo_root)
        last_commit_time = last_commit_timestamps.get(relative_path)
        if last_commit_time is None:
            skipped += 1
            progress.update(index)
            continue

        if not dry_run:
            os.utime(file_path, (last_commit_time, last_commit_time))
        restored += 1
        progress.update(index)

    return restored, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively restore file modification times to the timestamp of the "
            "last commit where each file was changed."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help=(
            "Path inside the target git repository. "
            "Defaults to the current working directory."
        ),
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

    repo_root = get_repo_root(args.root.resolve())
    file_paths = list_tracked_files(repo_root, args.paths)
    last_commit_timestamps = get_last_commit_timestamps(repo_root, args.paths)

    restored, skipped = restore_mtime(
        repo_root,
        file_paths,
        last_commit_timestamps,
        args.dry_run,
    )

    action = "Would restore" if args.dry_run else "Restored"
    print(f"{action} mtimes for {restored} file(s). Skipped {skipped} file(s).")


if __name__ == "__main__":
    main()
