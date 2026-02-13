#!/usr/bin/env python3
import argparse
import os
from pathlib import Path

from git_utils import get_last_commit_timestamps, get_repo_root, list_tracked_files
from progress_tracker import ProgressTracker


def restore_mtime(
    repo_root: Path,
    file_paths: list[Path],
    last_commit_timestamps: dict[Path, int],
    dry_run: bool,
) -> tuple[int, int]:
    restored = 0
    skipped = 0

    progress = ProgressTracker(
        len(file_paths),
        enabled_threshold=101,
        start_message=f"Processing {len(file_paths)} file(s)...",
        print_all_percent_transitions=True,
    )

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
