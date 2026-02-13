import argparse
import os
import time
from pathlib import Path


class ProgressTracker:
    def __init__(self, total: int) -> None:
        self.total = total
        self.enabled = total > 0
        self.start_monotonic = time.monotonic()
        self.processed = 0
        self.last_percent = -1

        if self.enabled:
            print(f"Total files to process: {self.total}")

    def step(self) -> None:
        if not self.enabled:
            return

        self.processed += 1
        percent = int((self.processed / self.total) * 100)
        if percent == self.last_percent:
            return

        self.last_percent = percent
        elapsed = time.monotonic() - self.start_monotonic
        per_item = elapsed / self.processed if self.processed else 0.0
        remaining = max(self.total - self.processed, 0)
        eta_seconds = int(per_item * remaining)
        print(
            f"Progress: {percent}% ({self.processed}/{self.total}), ETA: {eta_seconds}s"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively replace tabs with spaces (if set) and normalize line endings for files "
            "inside a directory."
        )
    )
    parser.add_argument("root_dir", help="Root directory to scan recursively.")
    parser.add_argument(
        "--spaces",
        type=int,
        default=0,
        help="How many spaces to use for each tab character (default: 0, do not change).",
    )
    parser.add_argument(
        "--line-ending",
        choices=["lf", "crlf", "cr"],
        default="lf",
        help="Target line ending type for all processed files (default: lf).",
    )
    parser.add_argument(
        "--include-binary",
        action="store_true",
        help="Also process files that look binary (default: skip them).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show progress and summary without changing files.",
    )
    return parser.parse_args()


def gather_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        base = Path(dirpath)
        for name in filenames:
            file_path = base / name
            if file_path.is_symlink():
                continue
            files.append(file_path)
    return files


def looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True

    sample = data[:4096]
    non_text = 0
    for byte in sample:
        if byte in (9, 10, 13):
            continue
        if 32 <= byte <= 126:
            continue
        if byte >= 128:
            continue
        non_text += 1

    return (non_text / len(sample)) > 0.30


def normalize_line_endings(data: bytes, line_ending: str) -> bytes:
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    if line_ending == "lf":
        return normalized
    if line_ending == "crlf":
        return normalized.replace(b"\n", b"\r\n")
    if line_ending == "cr":
        return normalized.replace(b"\n", b"\r")

    raise ValueError(f"Unsupported line ending type: {line_ending}")


def transform_content(data: bytes, spaces: int, line_ending: str) -> bytes:
    if spaces > 0:
        transformed = data.replace(b"\t", b" " * spaces)
    else:
        transformed = data
    transformed = normalize_line_endings(transformed, line_ending)
    return transformed


def process_file(
    file_path: Path,
    spaces: int,
    line_ending: str,
    include_binary: bool,
    dry_run: bool,
) -> tuple[bool, bool]:
    original = file_path.read_bytes()

    is_binary = looks_binary(original)
    if is_binary and not include_binary:
        return False, True

    transformed = transform_content(original, spaces, line_ending)
    if transformed == original:
        return False, False

    if dry_run:
        return True, False

    stat_before = file_path.stat()
    file_path.write_bytes(transformed)
    os.utime(file_path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    return True, False


def main() -> None:
    args = parse_args()

    if args.spaces < 0:
        raise SystemExit("--spaces must be >= 0")

    root = Path(args.root_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit("root_dir must be an existing directory")

    scan_start = time.monotonic()
    files = gather_files(root)
    scan_elapsed = time.monotonic() - scan_start
    print(f"Collected {len(files)} files in {scan_elapsed:.2f}s")

    tracker = ProgressTracker(len(files))

    changed = 0
    skipped_binary = 0
    errors = 0

    for file_path in files:
        try:
            file_changed, binary_skipped = process_file(
                file_path=file_path,
                spaces=args.spaces,
                line_ending=args.line_ending,
                include_binary=args.include_binary,
                dry_run=args.dry_run,
            )
            if file_changed:
                changed += 1
            if binary_skipped:
                skipped_binary += 1
        except OSError as exc:
            errors += 1
            print(f"Failed to process '{file_path}': {exc}")
        finally:
            tracker.step()

    mode = "dry-run" if args.dry_run else "apply"
    print(
        "Done "
        f"({mode}). Changed: {changed}, Skipped binary: {skipped_binary}, Errors: {errors}, "
        f"Total: {len(files)}"
    )


if __name__ == "__main__":
    main()
