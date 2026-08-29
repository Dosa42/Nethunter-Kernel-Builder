#!/usr/bin/env python3
"""Apply audited source-level compatibility fixes required by all-config."""

import argparse
import hashlib
import json
from pathlib import Path


START = "\tstruct __alloc_all_io_state {\n"
END = "\n\tif (pages) {\n"

REPLACEMENT = """\tsize_t ios_bytes = ore_io_state_size(numdevs);
\tsize_t sglist_bytes = sizeof(*sgilist) * sgs_per_dev * numdevs;
\tsize_t pages_bytes = sizeof(*pages) * num_par_pages;
\tsize_t extra_bytes = max(sglist_bytes, pages_bytes);
\tsize_t total_bytes = ios_bytes + extra_bytes;
\tvoid *extra_part;

\t/*
\t * The original code used variable-length arrays as structure members,
\t * a GCC extension that Clang intentionally rejects. Keep the same
\t * contiguous layout for small requests and the same split allocation for
\t * larger requests, but calculate the runtime sizes explicitly.
\t */
\tif (likely(total_bytes <= PAGE_SIZE)) {
\t\tios = kzalloc(total_bytes, GFP_KERNEL);
\t\tif (unlikely(!ios)) {
\t\t\tORE_DBGMSG("Failed kzalloc bytes=%zd\\n", total_bytes);
\t\t\t*pios = NULL;
\t\t\treturn -ENOMEM;
\t\t}
\t\textra_part = (u8 *)ios + ios_bytes;
\t} else {
\t\tios = kzalloc(ios_bytes, GFP_KERNEL);
\t\tif (unlikely(!ios)) {
\t\t\tORE_DBGMSG("Failed alloc first part bytes=%zd\\n", ios_bytes);
\t\t\t*pios = NULL;
\t\t\treturn -ENOMEM;
\t\t}
\t\textra_part = kzalloc(extra_bytes, GFP_KERNEL);
\t\tif (unlikely(!extra_part)) {
\t\t\tORE_DBGMSG("Failed alloc second part bytes=%zd\\n", extra_bytes);
\t\t\tkfree(ios);
\t\t\t*pios = NULL;
\t\t\treturn -ENOMEM;
\t\t}
\t\tios->extra_part_alloc = true;
\t}

\tpages = num_par_pages ? extra_part : NULL;
\tsgilist = sgs_per_dev ? extra_part : NULL;
"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()

    target = args.source_root / "fs/exofs/ore.c"
    before = target.read_bytes()
    text = before.decode()
    start = text.find(START)
    end = text.find(END, start)
    if start < 0 or end < 0:
        raise SystemExit("EXOFS allocator anchors not found; refusing blind patch")
    if text.find(START, start + 1) >= 0:
        raise SystemExit("EXOFS allocator start anchor is not unique")

    patched = text[:start] + REPLACEMENT + text[end:]
    if "struct __alloc_all_io_state" in patched:
        raise SystemExit("GCC-only EXOFS allocation structure remains")
    if "ore_io_state_size(numdevs)" not in patched:
        raise SystemExit("EXOFS runtime allocation replacement is incomplete")

    after = patched.encode()
    target.write_bytes(after)
    result = {
        "patches": [{
            "path": "fs/exofs/ore.c",
            "purpose": "replace GCC-only VLA-in-struct allocation with Clang-compatible runtime sizing",
            "before_sha256": sha256(before),
            "after_sha256": sha256(after),
            "feature_preserved": "CONFIG_EXOFS_FS",
        }]
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
