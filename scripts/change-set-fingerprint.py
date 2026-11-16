#!/usr/bin/env python3
"""Print a deterministic fingerprint for the current Git change set.

Includes HEAD, all staged/unstaged tracked changes relative to HEAD, and
non-ignored untracked paths with content hashes. It never prints file contents.
Ignored files (including ignored secret files) are intentionally excluded.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import stat
from pathlib import Path


def git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"git {' '.join(args)} failed ({result.returncode})")
    return result.stdout


def add_field(hasher: "hashlib._Hash", label: bytes, value: bytes) -> None:
    hasher.update(len(label).to_bytes(8, "big"))
    hasher.update(label)
    hasher.update(len(value).to_bytes(8, "big"))
    hasher.update(value)


def main() -> int:
    try:
        head = git("rev-parse", "HEAD").strip()
        tracked_diff = git("diff", "--binary", "HEAD", "--")
        status = git("status", "--porcelain=v1", "-z")
        untracked_raw = git("ls-files", "--others", "--exclude-standard", "-z")
        paths = sorted(path for path in untracked_raw.split(b"\0") if path)

        digest = hashlib.sha256()
        add_field(digest, b"head", head)
        add_field(digest, b"tracked-diff-from-head", tracked_diff)
        add_field(digest, b"working-tree-status", status)

        root = Path(git("rev-parse", "--show-toplevel").decode().strip())
        for raw_path in paths:
            path = root / os.fsdecode(raw_path)
            try:
                if path.is_symlink():
                    payload = b"symlink\0" + os.fsencode(os.readlink(path))
                elif path.is_file():
                    mode = stat.S_IMODE(path.stat().st_mode).to_bytes(4, "big")
                    payload = b"file\0" + mode + path.read_bytes()
                elif path.is_dir():
                    payload = b"directory"
                else:
                    payload = b"other"
            except OSError as exc:
                raise RuntimeError(f"cannot fingerprint untracked path {os.fsdecode(raw_path)!r}: {exc}") from exc
            file_hash = hashlib.sha256(payload).digest()
            add_field(digest, b"untracked-path", raw_path)
            add_field(digest, b"untracked-content-sha256", file_hash)

        print(f"HEAD: {head.decode()}")
        print(f"TRACKED_DIFF_SHA256: {hashlib.sha256(tracked_diff).hexdigest()}")
        print(f"UNTRACKED_FILES: {len(paths)}")
        print(f"CHANGESET_SHA256: {digest.hexdigest()}")
        return 0
    except (RuntimeError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
