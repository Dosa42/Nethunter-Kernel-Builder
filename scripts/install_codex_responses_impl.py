#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile
import tarfile

BEARSSL_REPO = "https://github.com/FatihBAKIR/BearSSL.git"
BEARSSL_COMMIT = "ae0766823801ffbe34ad62e25c83682110781b77"


def run(*argv: str, cwd: Path | None = None, stdout=None) -> None:
    print("+", " ".join(argv))
    subprocess.run(argv, cwd=str(cwd) if cwd else None, check=True, stdout=stdout)


def append_once(path: Path, text: str) -> None:
    s = path.read_text(encoding="utf-8")
    if text.strip() not in s:
        path.write_text(s.rstrip() + "\n" + text.rstrip() + "\n", encoding="utf-8")


def insert_once(path: Path, marker: str, block: str) -> None:
    s = path.read_text(encoding="utf-8")
    if block.strip() in s:
        return
    if marker not in s:
        raise RuntimeError(f"marker not found in {path}: {marker!r}")
    path.write_text(s.replace(marker, block.rstrip() + "\n\n" + marker, 1), encoding="utf-8")


def make_compat_headers(compat: Path) -> None:
    compat.mkdir(parents=True, exist_ok=True)
    (compat / "stddef.h").write_text(r'''#ifndef CODEX_BEARSSL_STDDEF_H
#define CODEX_BEARSSL_STDDEF_H
#include <linux/stddef.h>
#include <linux/types.h>
#ifndef NULL
#define NULL ((void *)0)
#endif
#endif
''', encoding="utf-8")
    (compat / "stdint.h").write_text(r'''#ifndef CODEX_BEARSSL_STDINT_H
#define CODEX_BEARSSL_STDINT_H
#include <linux/types.h>
typedef s8 int8_t;
typedef u8 uint8_t;
typedef s16 int16_t;
typedef u16 uint16_t;
typedef s32 int32_t;
typedef u32 uint32_t;
typedef s64 int64_t;
typedef u64 uint64_t;
typedef long intptr_t;
typedef unsigned long uintptr_t;
#define INT8_MIN (-128)
#define INT8_MAX 127
#define UINT8_MAX 255U
#define INT16_MIN (-32767 - 1)
#define INT16_MAX 32767
#define UINT16_MAX 65535U
#define INT32_MIN (-2147483647 - 1)
#define INT32_MAX 2147483647
#define UINT32_MAX 4294967295U
#define INT64_MIN (-9223372036854775807LL - 1)
#define INT64_MAX 9223372036854775807LL
#define UINT64_MAX 18446744073709551615ULL
#define INT8_C(x) x
#define UINT8_C(x) x##U
#define INT16_C(x) x
#define UINT16_C(x) x##U
#define INT32_C(x) x
#define UINT32_C(x) x##U
#define INT64_C(x) x##LL
#define UINT64_C(x) x##ULL
#endif
''', encoding="utf-8")
    (compat / "string.h").write_text(r'''#ifndef CODEX_BEARSSL_STRING_H
#define CODEX_BEARSSL_STRING_H
#include <linux/string.h>
#endif
''', encoding="utf-8")
    (compat / "limits.h").write_text(r'''#ifndef CODEX_BEARSSL_LIMITS_H
#define CODEX_BEARSSL_LIMITS_H
#define CHAR_BIT 8
#define SCHAR_MAX __SCHAR_MAX__
#define SCHAR_MIN (-SCHAR_MAX - 1)
#define UCHAR_MAX (SCHAR_MAX * 2U + 1U)
#define SHRT_MAX __SHRT_MAX__
#define SHRT_MIN (-SHRT_MAX - 1)
#define USHRT_MAX (SHRT_MAX * 2U + 1U)
#define INT_MAX __INT_MAX__
#define INT_MIN (-INT_MAX - 1)
#define UINT_MAX (INT_MAX * 2U + 1U)
#define LONG_MAX __LONG_MAX__
#define LONG_MIN (-LONG_MAX - 1L)
#define ULONG_MAX (LONG_MAX * 2UL + 1UL)
#define LLONG_MAX __LONG_LONG_MAX__
#define LLONG_MIN (-LLONG_MAX - 1LL)
#define ULLONG_MAX (LLONG_MAX * 2ULL + 1ULL)
#endif
''', encoding="utf-8")
    (compat / "time.h").write_text(r'''#ifndef CODEX_BEARSSL_TIME_H
#define CODEX_BEARSSL_TIME_H
typedef long time_t;
#endif
''', encoding="utf-8")


def patch_bearssl_config(config: Path) -> None:
    s = config.read_text(encoding="utf-8")
    marker = "#define CONFIG_H__\n"
    block = r'''
/* Codex kernel build: no hosted OS entropy/time or non-AArch64 intrinsics. */
#define BR_USE_GETENTROPY 0
#define BR_USE_URANDOM 0
#define BR_USE_WIN32_RAND 0
#define BR_USE_UNIX_TIME 0
#define BR_USE_WIN32_TIME 0
#define BR_RDRAND 0
#define BR_AES_X86NI 0
#define BR_SSE2 0
#define BR_POWER8 0
#define BR_64 1
#define BR_INT128 1
#define BR_LE_UNALIGNED 1
'''
    if block.strip() not in s:
        if marker not in s:
            raise RuntimeError("BearSSL config marker not found")
        s = s.replace(marker, marker + block + "\n", 1)
        config.write_text(s, encoding="utf-8")


def generate_bearssl_makefile(bear: Path) -> None:
    objects = []
    for p in sorted((bear / "src").rglob("*.c")):
        rel = p.relative_to(bear).as_posix()
        if rel == "src/rand/sysrng.c":
            continue
        objects.append(rel[:-2] + ".o")
    lines = [
        "# Generated from pinned BearSSL source for the built-in A32 kernel.",
        "obj-y += bearssl_kernel.o",
        "bearssl_kernel-y := \\",
    ]
    for i, obj in enumerate(objects):
        tail = " \\" if i != len(objects) - 1 else ""
        lines.append(f"\t{obj}{tail}")
    lines += [
        "ccflags-y += -I$(src)/compat -I$(src)/inc -I$(src)/src -ffreestanding -std=gnu99",
        "ccflags-y += -Wno-declaration-after-statement -Wno-unused-function -Wno-unused-const-variable",
        "",
    ]
    (bear / "Makefile").write_text("\n".join(lines), encoding="utf-8")


def prepare_bearssl(dst: Path, ca_bundle: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="codex-bearssl-") as td:
        td = Path(td)
        src = td / "BearSSL"
        build = td / "build"
        run("git", "init", str(src))
        run("git", "-C", str(src), "remote", "add", "origin", BEARSSL_REPO)
        run("git", "-C", str(src), "fetch", "--depth=1", "origin", BEARSSL_COMMIT)
        run("git", "-C", str(src), "checkout", "--detach", "FETCH_HEAD")
        got = subprocess.check_output(["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()
        if got != BEARSSL_COMMIT:
            raise RuntimeError(f"BearSSL revision mismatch: {got}")

        # Host-only generator. This executable is never copied into the kernel.
        run("cmake", "-S", str(src), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release")
        run("cmake", "--build", str(build), "--target", "brssl", "-j2")
        brssl = build / "tools" / "brssl"
        if not brssl.is_file():
            raise RuntimeError("BearSSL brssl host generator was not built")

        bear = dst / "bearssl"
        if bear.exists():
            shutil.rmtree(bear)
        bear.mkdir(parents=True)
        shutil.copytree(src / "inc", bear / "inc")
        shutil.copytree(src / "src", bear / "src")
        shutil.copy2(src / "LICENSE.txt", bear / "LICENSE.txt")
        (bear / "UPSTREAM_COMMIT").write_text(BEARSSL_COMMIT + "\n", encoding="utf-8")
        patch_bearssl_config(bear / "src" / "config.h")
        make_compat_headers(bear / "compat")
        generate_bearssl_makefile(bear)

        trust = dst / "codex_trust_anchors.h"
        with trust.open("wb") as f:
            run(str(brssl), "ta", "-q", str(ca_bundle), stdout=f)
        ts = trust.read_text(encoding="utf-8")
        if "br_x509_trust_anchor TAs" not in ts or "TAs_NUM" not in ts:
            raise RuntimeError("generated BearSSL trust anchor header is invalid")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", required=True, type=Path)
    ap.add_argument("--payload-root", required=True, type=Path)
    ap.add_argument("--ca-bundle", type=Path, default=Path("/etc/ssl/certs/ca-certificates.crt"))
    args = ap.parse_args()
    src = args.source_root.resolve()
    payload = args.payload_root.resolve()
    payload_tmp = None
    archive = payload / "kernel-native-payload.tar.gz"
    if archive.is_file():
        payload_tmp = Path(tempfile.mkdtemp(prefix="codex-kernel-payload-"))
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(payload_tmp)
        payload = payload_tmp

    dst = src / "drivers/misc/codex_responses"
    dst.mkdir(parents=True, exist_ok=True)
    names = (
        "codex_kernel.h",
        "codex_oauth.c",
        "codex_token_store.c",
        "codex_responses.c",
        "codex_responses_hw.c",
        "Kconfig",
        "Makefile",
    )
    for name in names:
        shutil.copy2(payload / name, dst / name)

    prepare_bearssl(dst, args.ca_bundle)

    append_once(src / "drivers/misc/Makefile", "obj-$(CONFIG_CODEX_RESPONSES) += codex_responses/")
    append_once(src / "drivers/misc/Kconfig", 'source "drivers/misc/codex_responses/Kconfig"')
    append_once(src / "arch/arm64/configs/a32x_defconfig", "CONFIG_CODEX_RESPONSES=y")

    target = src / "drivers/misc/mediatek/flashlight/flashlights-mt6360.c"
    marker = "/******************************************************************************\n * Timer and work queue"
    block = r'''int codex_mt6360_set_torch(int state)
{
    int ret;

    if (!flashlight_dev_ch1)
        return -ENODEV;

    if (!state) {
        mt6360_en_ch1 = MT6360_DISABLE;
        mt6360_en_ch2 = MT6360_DISABLE;
        return mt6360_disable_all();
    }

    ret = mt6360_set_level_ch1(0);
    if (ret < 0)
        return ret;

    mt6360_en_ch1 = MT6360_ENABLE_TORCH;
    mt6360_en_ch2 = MT6360_DISABLE;
    return mt6360_enable();
}
EXPORT_SYMBOL_GPL(codex_mt6360_set_torch);'''
    insert_once(target, marker, block)

    if payload_tmp is not None:
        shutil.rmtree(payload_tmp)
    print("Codex kernel-native OAuth/token/Responses + BearSSL installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
