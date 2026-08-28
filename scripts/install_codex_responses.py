#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import subprocess
import sys

EXPECTED_SHA256 = "9a622ac7e343e19fbff1ea6567823845be17be6a30cf0d3a0de9d17afe48a303"

STDINT_COMPAT = r'''#ifndef CODEX_BEARSSL_STDINT_H
#define CODEX_BEARSSL_STDINT_H
#include <linux/types.h>
#ifndef INT8_MIN
#define INT8_MIN (-128)
#endif
#ifndef INT8_MAX
#define INT8_MAX 127
#endif
#ifndef UINT8_MAX
#define UINT8_MAX 255U
#endif
#ifndef INT16_MIN
#define INT16_MIN (-32767 - 1)
#endif
#ifndef INT16_MAX
#define INT16_MAX 32767
#endif
#ifndef UINT16_MAX
#define UINT16_MAX 65535U
#endif
#ifndef INT32_MIN
#define INT32_MIN (-2147483647 - 1)
#endif
#ifndef INT32_MAX
#define INT32_MAX 2147483647
#endif
#ifndef UINT32_MAX
#define UINT32_MAX 4294967295U
#endif
#ifndef INT64_MIN
#define INT64_MIN (-9223372036854775807LL - 1)
#endif
#ifndef INT64_MAX
#define INT64_MAX 9223372036854775807LL
#endif
#ifndef UINT64_MAX
#define UINT64_MAX 18446744073709551615ULL
#endif
#ifndef INT8_C
#define INT8_C(x) x
#endif
#ifndef UINT8_C
#define UINT8_C(x) x##U
#endif
#ifndef INT16_C
#define INT16_C(x) x
#endif
#ifndef UINT16_C
#define UINT16_C(x) x##U
#endif
#ifndef INT32_C
#define INT32_C(x) x
#endif
#ifndef UINT32_C
#define UINT32_C(x) x##U
#endif
#ifndef INT64_C
#define INT64_C(x) x##LL
#endif
#ifndef UINT64_C
#define UINT64_C(x) x##ULL
#endif
#endif
'''


def source_root_from_argv() -> Path:
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--source-root" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
        if arg.startswith("--source-root="):
            return Path(arg.split("=", 1)[1]).resolve()
    return Path.cwd().resolve()


def patch_codex_oauth_sock_header(source_root: Path) -> None:
    oauth = source_root / "drivers/misc/codex_responses/codex_oauth.c"
    text = oauth.read_text(encoding="utf-8")
    header = "#include <net/sock.h>\n"
    if header not in text:
        oauth.write_text(header + text, encoding="utf-8")
        print(f"patched Linux 4.14 struct sock definition: {oauth}")


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    payload = repo / "codex" / "kernel"
    chunks = sorted(payload.glob("kernel-native-payload.b64.*"))
    if not chunks:
        raise RuntimeError("kernel-native Codex payload chunks are missing")

    encoded = "".join(p.read_text(encoding="ascii").strip() for p in chunks)
    raw = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"kernel-native Codex payload SHA-256 mismatch: {digest}")

    archive = payload / "kernel-native-payload.tar.gz"
    archive.write_bytes(raw)
    print(f"reconstructed {archive} sha256={digest} size={len(raw)}")

    impl = Path(__file__).resolve().with_name("install_codex_responses_impl.py")
    completed = subprocess.run([sys.executable, str(impl), *sys.argv[1:]])
    if completed.returncode != 0:
        return completed.returncode

    source_root = source_root_from_argv()

    compat = source_root / "drivers/misc/codex_responses/bearssl/compat/stdint.h"
    compat.write_text(STDINT_COMPAT, encoding="utf-8")
    print(f"patched BearSSL stdint compatibility: {compat}")

    patch_codex_oauth_sock_header(source_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
