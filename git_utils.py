from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileCommitDescription:
    commit_hash: str
    commit_date: str
    description: str


@dataclass
class GitHistoryInfo:
    is_git_repo: bool
    file_commit_timestamps: dict[str, int]
    added_never_modified_files: set[str]


@dataclass
class RepoMetadata:
    root: Path
    is_git_repo: bool
    description_cache: dict[str, FileCommitDescription | None]


def run_git_command(repo_root: Path, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo_root.as_posix(), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def run_git_stdout(repo_root: Path, args: list[str]) -> str:
    completed = run_git_command(repo_root, args, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def is_git_repo(repo_root: Path) -> bool:
    repo_check = run_git_command(repo_root, ["rev-parse", "--is-inside-work-tree"], check=False)
    return repo_check.returncode == 0 and repo_check.stdout.strip().lower() == "true"


def get_repo_root(start: Path) -> Path:
    completed = run_git_command(start, ["rev-parse", "--show-toplevel"], check=False)
    if completed.returncode != 0:
        raise SystemExit("Current directory is not inside a git repository.")
    return Path(completed.stdout.strip())


def get_path_prefix(repo_root: Path) -> str:
    toplevel_result = run_git_command(repo_root, ["rev-parse", "--show-toplevel"], check=False)
    if toplevel_result.returncode != 0:
        return ""

    repo_top_level = Path(toplevel_result.stdout.strip()).resolve()
    try:
        path_prefix = repo_root.resolve().relative_to(repo_top_level)
        path_prefix_str = path_prefix.as_posix()
        return "" if path_prefix_str == "." else path_prefix_str
    except ValueError:
        return ""


def normalize_git_path(log_path: str, path_prefix_str: str) -> str | None:
    rel = Path(log_path).as_posix()
    if not path_prefix_str:
        return rel

    prefix = f"{path_prefix_str}/"
    if rel == path_prefix_str:
        return ""
    if rel.startswith(prefix):
        return rel[len(prefix):]
    return None


def is_commit_ancestor(
    repo_root: Path,
    ancestor_commit: str,
    descendant_commit: str,
    cache: dict[tuple[str, str, str], bool],
) -> bool:
    cache_key = (repo_root.as_posix(), ancestor_commit, descendant_commit)
    if cache_key in cache:
        return cache[cache_key]

    result = run_git_command(
        repo_root,
        ["merge-base", "--is-ancestor", ancestor_commit, descendant_commit],
        check=False,
    )
    is_ancestor = result.returncode == 0
    cache[cache_key] = is_ancestor
    return is_ancestor


def collect_recent_file_descriptions(repo_root: Path) -> dict[str, FileCommitDescription | None]:
    path_prefix_str = get_path_prefix(repo_root)
    result = run_git_command(
        repo_root,
        [
            "log",
            "--first-parent",
            "--reverse",
            "--name-only",
            "--date=format:%Y-%m-%d %H:%M:%S %z",
            "--pretty=format:__COMMIT__%n%H%n%ad%n%s",
            "--diff-filter=AM",
            "HEAD",
        ],
        check=False,
    )
    if result.returncode != 0:
        return {}

    descriptions: dict[str, FileCommitDescription | None] = {}
    current_commit_hash: str | None = None
    current_commit_date: str | None = None
    current_commit_subject: str | None = None

    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line == "__COMMIT__":
            current_commit_hash = None
            current_commit_date = None
            current_commit_subject = None
            continue

        if current_commit_hash is None:
            current_commit_hash = line
            continue

        if current_commit_date is None:
            current_commit_date = line
            continue

        if current_commit_subject is None:
            current_commit_subject = line
            continue

        normalized_path = normalize_git_path(line, path_prefix_str)
        if not normalized_path:
            continue

        descriptions[normalized_path] = FileCommitDescription(
            commit_hash=current_commit_hash,
            commit_date=current_commit_date,
            description=current_commit_subject,
        )

    return descriptions


def build_repo_metadata(repo_root: Path) -> RepoMetadata:
    repo_is_git = is_git_repo(repo_root)
    description_cache: dict[str, FileCommitDescription | None] = {}
    if repo_is_git:
        description_cache = collect_recent_file_descriptions(repo_root)

    return RepoMetadata(root=repo_root, is_git_repo=repo_is_git, description_cache=description_cache)


def get_file_description(repo: RepoMetadata, rel_path: str) -> FileCommitDescription | None:
    if rel_path in repo.description_cache:
        return repo.description_cache[rel_path]

    if not repo.is_git_repo:
        repo.description_cache[rel_path] = None
        return None

    result = run_git_command(
        repo.root,
        [
            "log",
            "--first-parent",
            "-1",
            "--date=format:%Y-%m-%d %H:%M:%S %z",
            "--format=%H%n%ad%n%s",
            "--",
            rel_path,
        ],
        check=False,
    )
    if result.returncode != 0:
        repo.description_cache[rel_path] = None
        return None

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 3:
        repo.description_cache[rel_path] = None
        return None

    description = FileCommitDescription(commit_hash=lines[0], commit_date=lines[1], description=lines[2])
    repo.description_cache[rel_path] = description
    return description


def collect_git_history_info(repo_root: Path) -> GitHistoryInfo:
    return collect_git_history_info_with_ignored_modification_commits(repo_root, set())


def load_commit_list(file_path: Path) -> set[str]:
    commits: set[str] = set()
    with file_path.open("r", encoding="utf-8") as commit_file:
        for line_number, raw_line in enumerate(commit_file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            if any(ch.isspace() for ch in line):
                raise ValueError(
                    "Invalid commit list line "
                    f"{line_number}: commit hash must not contain spaces"
                )

            commits.add(line.lower())

    return commits


def resolve_commit_hashes(repo_root: Path, commit_refs: set[str]) -> set[str]:
    resolved_commits: set[str] = set()
    for commit_ref in commit_refs:
        commit = commit_ref.strip().lower()
        if not commit:
            continue

        resolved = run_git_command(
            repo_root,
            ["rev-parse", "--verify", f"{commit}^{{commit}}"],
            check=False,
        )
        if resolved.returncode == 0:
            resolved_commits.add(resolved.stdout.strip().lower())
            continue

        # Keep the original token as a fallback. This allows prefix matching below
        # even when the ref cannot be resolved in the current repository state.
        resolved_commits.add(commit)

    return resolved_commits


def collect_git_history_info_with_ignored_modification_commits(
    repo_root: Path,
    ignored_modification_commits: set[str],
) -> GitHistoryInfo:
    if not is_git_repo(repo_root):
        return GitHistoryInfo(False, {}, set())

    resolved_ignored_modification_commits = resolve_commit_hashes(
        repo_root,
        ignored_modification_commits,
    )

    path_prefix_str = get_path_prefix(repo_root)
    log_result = run_git_command(
        repo_root,
        [
            "log",
            "--first-parent",
            "--reverse",
            "--name-only",
            "--pretty=format:__COMMIT__ %ct",
            "--diff-filter=AM",
            "HEAD",
        ],
        check=True,
    )

    file_commit_timestamps: dict[str, int] = {}
    current_timestamp: int | None = None
    for raw_line in log_result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("__COMMIT__ "):
            current_timestamp = int(line.split(maxsplit=1)[1])
            continue

        if current_timestamp is None:
            continue
        normalized_line = normalize_git_path(line, path_prefix_str)
        if not normalized_line:
            continue

        file_commit_timestamps[normalized_line] = current_timestamp

    status_log_result = run_git_command(
        repo_root,
        [
            "log",
            "--first-parent",
            "--name-status",
            "--pretty=format:__COMMIT__ %H",
            "--diff-filter=AM",
            "HEAD",
        ],
        check=True,
    )

    all_added_files: set[str] = set()
    all_modified_files: set[str] = set()
    current_commit_hash: str | None = None
    for raw_line in status_log_result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("__COMMIT__"):
            parts = line.split(maxsplit=1)
            current_commit_hash = parts[1] if len(parts) == 2 else None
            continue

        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, rel_path = parts
        normalized_path = normalize_git_path(rel_path, path_prefix_str)
        if not normalized_path:
            continue

        if status == "A":
            all_added_files.add(normalized_path)
        elif status == "M":
            normalized_commit_hash = (current_commit_hash or "").lower()
            commit_is_ignored = any(
                normalized_commit_hash == ignored
                or normalized_commit_hash.startswith(ignored)
                for ignored in resolved_ignored_modification_commits
            )
            if commit_is_ignored:
                continue
            all_modified_files.add(normalized_path)

    return GitHistoryInfo(
        True,
        file_commit_timestamps,
        all_added_files - all_modified_files,
    )


def list_tracked_files(repo_root: Path, pathspecs: list[str]) -> list[Path]:
    output = run_git_stdout(repo_root, ["ls-files", "-z", "--", *pathspecs])
    entries = [item for item in output.split("\0") if item]
    return [repo_root / item for item in entries]


def get_last_commit_timestamps(repo_root: Path, pathspecs: list[str]) -> dict[Path, int]:
    output = run_git_stdout(repo_root, ["log", "--format=__COMMIT__%ct", "--name-only", "--", *pathspecs])

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
