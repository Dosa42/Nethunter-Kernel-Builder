#!/usr/bin/env python3
"""Apply audited source-level compatibility fixes required by all-config."""

import argparse
import hashlib
import json
from pathlib import Path


ORE_START = "\tstruct __alloc_all_io_state {\n"
ORE_END = "\n\tif (pages) {\n"

ORE_REPLACEMENT = """\tsize_t ios_bytes = ore_io_state_size(numdevs);
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

ORE_RAID_START = "\tstruct _alloc_all_bytes {\n"
ORE_RAID_END = "\n\tsp2d->parity = parity;\n"

ORE_RAID_REPLACEMENT = """\t/*
\t * Desired allocation layout is, though when larger than PAGE_SIZE,
\t * each per-stripe array is separately allocated.  Use byte offsets
\t * instead of GCC's VLA-in-struct extension so Clang accepts it.
\t */
\tchar *__a1pa;
\tchar *__a1pa_end;
\tconst size_t sizeof_stripe_pages_2d =
\t\tsizeof(struct __stripe_pages_2d) +
\t\tsizeof(struct __1_page_stripe) * pages_in_unit;
\tconst size_t sizeof__a1pa =
\t\tALIGN(sizeof(struct page *) * (2 * group_width) + data_devs,
\t\t      sizeof(void *));
\tconst size_t sizeof__a1pa_arrays = sizeof__a1pa * pages_in_unit;
\tconst size_t alloc_total = sizeof_stripe_pages_2d +
\t\t\t\t   sizeof__a1pa_arrays;
\tunsigned num_a1pa, alloc_size, i;

\t/* FIXME: check these numbers in ore_verify_layout */
\tBUG_ON(sizeof_stripe_pages_2d > PAGE_SIZE);
\tBUG_ON(sizeof__a1pa > PAGE_SIZE);

\tif (alloc_total > PAGE_SIZE) {
\t\tnum_a1pa = (PAGE_SIZE - sizeof_stripe_pages_2d) / sizeof__a1pa;
\t\talloc_size = sizeof_stripe_pages_2d + sizeof__a1pa * num_a1pa;
\t} else {
\t\tnum_a1pa = pages_in_unit;
\t\talloc_size = alloc_total;
\t}

\t*psp2d = sp2d = kzalloc(alloc_size, GFP_KERNEL);
\tif (unlikely(!sp2d)) {
\t\tORE_DBGMSG("!! Failed to alloc sp2d size=%d\\n", alloc_size);
\t\treturn -ENOMEM;
\t}
\t/* From here just call _sp2d_free. */

\t__a1pa = (char *)sp2d + sizeof_stripe_pages_2d;
\t__a1pa_end = (char *)sp2d + alloc_size;

\tfor (i = 0; i < pages_in_unit; ++i) {
\t\tstruct __1_page_stripe *stripe = &sp2d->_1p_stripes[i];

\t\tif (unlikely(__a1pa >= __a1pa_end)) {
\t\t\tnum_a1pa = min_t(unsigned, PAGE_SIZE / sizeof__a1pa,
\t\t\t\t\t\t\tpages_in_unit - i);
\t\t\talloc_size = sizeof__a1pa * num_a1pa;
\t\t\t__a1pa = kzalloc(alloc_size, GFP_KERNEL);
\t\t\tif (unlikely(!__a1pa)) {
\t\t\t\tORE_DBGMSG("!! Failed to _alloc_1p_arrays=%d\\n",
\t\t\t\t\t   num_a1pa);
\t\t\t\treturn -ENOMEM;
\t\t\t}
\t\t\t__a1pa_end = __a1pa + alloc_size;
\t\t\tstripe->alloc = true;
\t\t}

\t\tstripe->pages = (void *)__a1pa;
\t\tstripe->scribble = stripe->pages + group_width;
\t\tstripe->page_is_read = (char *)stripe->scribble + group_width;
\t\t__a1pa += sizeof__a1pa;
\t}
"""

LINUXINCLUDE_ANCHOR = "\t\t-I$(srctree)/drivers/misc/mediatek/include \\\n"
MTPROF_INCLUDE = "\t\t-I$(srctree)/drivers/misc/mediatek/mtprof \\\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_anchored(text: str, start_anchor: str, end_anchor: str,
                     replacement: str, label: str) -> str:
    start = text.find(start_anchor)
    end = text.find(end_anchor, start)
    if start < 0 or end < 0:
        raise SystemExit(f"{label} anchors not found; refusing blind patch")
    if text.find(start_anchor, start + 1) >= 0:
        raise SystemExit(f"{label} start anchor is not unique")
    return text[:start] + replacement + text[end:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()

    patches = []

    target = args.source_root / "fs/exofs/ore.c"
    before = target.read_bytes()
    patched = replace_anchored(before.decode(), ORE_START, ORE_END,
                               ORE_REPLACEMENT, "EXOFS allocator")
    if "struct __alloc_all_io_state" in patched:
        raise SystemExit("GCC-only EXOFS allocation structure remains")
    if "ore_io_state_size(numdevs)" not in patched:
        raise SystemExit("EXOFS runtime allocation replacement is incomplete")

    after = patched.encode()
    target.write_bytes(after)
    patches.append({
        "path": "fs/exofs/ore.c",
        "purpose": "replace GCC-only VLA-in-struct allocation with Clang-compatible runtime sizing",
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
        "feature_preserved": "CONFIG_EXOFS_FS",
    })

    target = args.source_root / "fs/exofs/ore_raid.c"
    before = target.read_bytes()
    patched = replace_anchored(before.decode(), ORE_RAID_START, ORE_RAID_END,
                               ORE_RAID_REPLACEMENT,
                               "EXOFS RAID allocator")
    if "struct _alloc_all_bytes" in patched:
        raise SystemExit("GCC-only EXOFS RAID allocation structure remains")
    if "sizeof_stripe_pages_2d" not in patched:
        raise SystemExit("EXOFS RAID runtime allocation replacement is incomplete")
    after = patched.encode()
    target.write_bytes(after)
    patches.append({
        "path": "fs/exofs/ore_raid.c",
        "purpose": "port the upstream runtime-sized RAID allocator that replaces GCC-only VLA structure members",
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
        "feature_preserved": "CONFIG_EXOFS_FS",
    })

    target = args.source_root / "Makefile"
    before = target.read_bytes()
    text = before.decode()
    if text.count(LINUXINCLUDE_ANCHOR) != 1:
        raise SystemExit("top-level MediaTek include anchor is not unique")
    if MTPROF_INCLUDE in text:
        raise SystemExit("MTPROF global include path already exists")
    patched = text.replace(LINUXINCLUDE_ANCHOR,
                           LINUXINCLUDE_ANCHOR + MTPROF_INCLUDE, 1)
    after = patched.encode()
    target.write_bytes(after)
    patches.append({
        "path": "Makefile",
        "purpose": "expose the genuine MediaTek mtprof header to core files that include bootprof.h",
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
        "feature_preserved": "CONFIG_MTPROF",
        "source": "drivers/misc/mediatek/mtprof/bootprof.h",
    })

    result = {"patches": patches}
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
