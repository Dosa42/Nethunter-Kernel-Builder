#!/usr/bin/env python3
"""Install published GPL source required by the exhaustive A32x configuration."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

UPSTREAM_REPOSITORY = "XayahSuSuSu/kernel_redmi_mt6885"
UPSTREAM_COMMIT = "007562b79057594114cf432bb7b7b21b22710436"
BASE_URL = (
    "https://raw.githubusercontent.com/"
    f"{UPSTREAM_REPOSITORY}/{UPSTREAM_COMMIT}/"
)
FILES = {
    "sound/soc/mediatek/audio_dsp/mt6885/Makefile":
        "7f91a3692223584384e0a4cf34f690527859a88c",
    "sound/soc/mediatek/audio_dsp/mt6885/dsp-platform-mem-control.c":
        "ddbd2675cf9bf326c22bd0225825f284b0d4a5d1",
    "sound/soc/mediatek/audio_dsp/mt6885/dsp-platform-mem-control.h":
        "eaddaab1123fffc6e3942af9e74bb523bc261493",
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()

    installed = []
    for relative, expected_sha in FILES.items():
        url = BASE_URL + relative
        request = Request(url, headers={"User-Agent": "A32x-Nethunter-Kernel-Builder"})
        with urlopen(request, timeout=60) as response:
            data = response.read()
        actual_sha = git_blob_sha(data)
        if actual_sha != expected_sha:
            raise SystemExit(
                f"integrity failure for {relative}: expected {expected_sha}, got {actual_sha}"
            )
        target = args.source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        installed.append({
            "path": relative,
            "bytes": len(data),
            "git_blob_sha": actual_sha,
            "url": url,
        })

    manifest = {
        "upstream_repository": UPSTREAM_REPOSITORY,
        "upstream_commit": UPSTREAM_COMMIT,
        "license_context": "published Linux kernel GPL source",
        "installed": installed,
        "unavailable_source_symbols": [{
            "symbol": "CONFIG_TOUCHSCREEN_MTK_SOLOMON",
            "expected_path": "drivers/input/touchscreen/mediatek/SOLOMON",
            "reason": (
                "MediaTek Kconfig/Makefile references the directory, but the "
                "implementation is absent from published MT6853/MTK 4.14 GPL trees."
            ),
        }],
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
