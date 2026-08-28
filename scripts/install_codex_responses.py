#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import subprocess
import sys

EXPECTED_SHA256 = "9a622ac7e343e19fbff1ea6567823845be17be6a30cf0d3a0de9d17afe48a303"


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
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
