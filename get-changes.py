import argparse
import hashlib
import time

from pathlib import Path
from collections import defaultdict

DEFAULT_EXCLUDES = {
    ".git", ".svn", ".hg",
    "Library", "Temp", "Obj", 
    "Logs", "UserSettings", 
    "Build", "Builds",
    ".idea", ".vs",
}

def should_skip(rel_parts, exclude_names):
    # Skip if any path segment matches exclude dir name
    return any(part in exclude_names for part in rel_parts)

def file_hash(path: Path, chunk_size=1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def collect_files(root: Path, exclude_names: set[str]) -> dict[str, tuple[int, int, Path]]:
    out = {}
    root = root.resolve()

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if should_skip(rel.parts, exclude_names):
            continue

        size = p.stat().st_size
        t = p.stat().st_mtime
        out[rel.as_posix()] = (size, t, p)
        
    return out

def ext_key(rel_path: str) -> str:
    name = Path(rel_path).name
    suf = Path(name).suffix.lower()
    return suf[1:] if suf.startswith(".") and len(suf) > 1 else "(no_ext)"

def main():
    ap = argparse.ArgumentParser(description="Compare two directories: added/modified/deleted, sorted by extension.")
    ap.add_argument("old_dir")
    ap.add_argument("new_dir")
    ap.add_argument("--include-deleted", action="store_true", help="Also print deleted files.")
    ap.add_argument("--exclude", action="append", default=[], help="Exclude directory name (can repeat).")
    ap.add_argument("--no-group", action="store_true", help="Print plain sorted list, no # extension headers.")
    ap.add_argument("--ignore-meta", action="store_true", help="Ignore Unity .meta files.")
    ap.add_argument("--size-asc", action="store_true", help="Sort by size ascending (default: descending).")
    ap.add_argument("--output-file", help="Redirect output to the file.")
    args = ap.parse_args()

    exclude = set(DEFAULT_EXCLUDES)
    exclude.update(args.exclude)

    old_root = Path(args.old_dir)
    new_root = Path(args.new_dir)

    if not old_root.exists() or not new_root.exists():
        raise SystemExit("Old or new directory does not exist.")
    
    start = time.time()
    print("Collecting old files.")
    old_idx = collect_files(old_root, exclude)
    print(f"Collected old files in {time.time() - start} seconds")
    
    start = time.time()
    print("Collecting new files.")
    new_idx = collect_files(new_root, exclude)
    print(f"Collected new files in {time.time() - start} seconds")

    added = []
    modified = []
    deleted = []

    count = len(new_idx)
    idx = 0
    prev_complete = -1

    for p, (size, t, path) in new_idx.items():
        idx += 1
        cur_complete = int(idx / count * 100);
        if cur_complete != prev_complete:
            print(f"Processed {cur_complete}%")
            prev_complete = cur_complete
        if args.ignore_meta and p.endswith(".meta"):
            continue
        if p not in old_idx:
            added.append(p)
        else:
            old_info = old_idx[p]
            if old_info[0] == size and old_info[1] == t:
                old_hash = file_hash(old_info[2])
                new_hash = file_hash(p)
                if old_hash != new_hash:
                    modified.append(p)
            else:
                modified.append(p)

    if args.include_deleted:
        for p in old_idx.keys():
            if args.ignore_meta and p.endswith(".meta"):
                continue
            if p not in new_idx:
                deleted.append(p)
    
    def new_size(p: str) -> int:
        return new_idx.get(p, (0, ""))[0]

    def old_size(p: str) -> int:
        return old_idx.get(p, (0, ""))[0]

    size_desc = not args.size_asc

    def sort_items(items, size_fn):
        def key(p: str):
            s = size_fn(p)
            s_key = -s if size_desc else s
            return (ext_key(p), s_key, p.lower())
        return sorted(items, key=key)

    added = sort_items(added, new_size)
    modified = sort_items(modified, new_size)
    deleted = sort_items(deleted, old_size)

    def generate_grouped_log(title, items, size_fn):
        lines = []
        lines.append(f"\n[{title}]: {len(items)}")
        max_path_len = max(len(p) for p in items)
        if args.no_group:
            for p in items:
                size = size_fn(p)
                lines.append(f"{p:<{max_path_len}}: {size:<10}")
            return
        buckets = defaultdict(list)
        for p in items:
            buckets[ext_key(p)].append(p)
        for ext in sorted(buckets.keys()):
            bucket = buckets[ext]
            lines.append(f"\n[{ext}]: {len(bucket)}")
            bucket.sort(
                key=lambda p: ((-size_fn(p) if size_desc else size_fn(p)), p.lower())
            )
            for p in bucket:
                size = size_fn(p)
                lines.append(f"{p:<{max_path_len}}: {size:<10}")
        return lines
    
    title_line = f"\n// ==== PROCESSED {count} FILES ====\n"
    print(title_line)

    lines = [title_line]

    added_lines = generate_grouped_log("ADDED", added, new_size)
    lines += added_lines
    modified_lines = generate_grouped_log("MODIFIED", modified, new_size)
    lines += modified_lines
    if args.include_deleted:
        deleted_lines = generate_grouped_log("DELETED", deleted, old_size)
        lines += deleted_lines
    content = "\n".join(lines)
    if args.output_file:
        output_file_path = Path(args.output_file)
        output_file_path_abs = output_file_path.resolve()
        with open(output_file_path_abs, "w", encoding="utf-8") as f:
            f.write(content)
            print(f"Diff log was written to '{output_file_path_abs}'")
    else:
        print(content)

if __name__ == "__main__":
    main()
