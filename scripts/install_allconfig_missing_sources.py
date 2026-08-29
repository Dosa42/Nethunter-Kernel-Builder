#!/usr/bin/env python3
"""Install published GPL source required by the exhaustive A32x configuration."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SOURCES = [
    {
        "repository": "XayahSuSuSu/kernel_redmi_mt6885",
        "commit": "007562b79057594114cf432bb7b7b21b22710436",
        "path": "sound/soc/mediatek/audio_dsp/mt6885",
    },
    {
        "repository": "LineageOS/android_kernel_xiaomi_mt6785",
        "commit": "a48fdea87dcfaab1d216c2fa99e49aa3722df2e9",
        "path": "sound/soc/mediatek/mt6785",
    },
    {
        "repository": "XayahSuSuSu/kernel_redmi_mt6885",
        "commit": "007562b79057594114cf432bb7b7b21b22710436",
        "path": "sound/soc/mediatek/mt6873",
    },
    {
        "repository": "XayahSuSuSu/kernel_redmi_mt6885",
        "commit": "007562b79057594114cf432bb7b7b21b22710436",
        "path": "sound/soc/mediatek/mt6885",
    },
    {
        "repository": "XayahSuSuSu/kernel_redmi_mt6885",
        "commit": "007562b79057594114cf432bb7b7b21b22710436",
        "path": "drivers/misc/mediatek/adsp/mt6885",
    },
    {
        "repository": "OnePlusOSS/android_kernel_oneplus_mt6893",
        "commit": "48f1797695e24d46986a7c87dd91dd21cbf8c342",
        "path": "drivers/input/touchscreen/mediatek/focaltech_touch",
    },
    {
        "repository": "xiaomi-mt6853-devs/android_kernel_xiaomi_cannon",
        "commit": "61923102fe542f96a4a993b78760c975c0b7508f",
        "path": "sound/soc/mediatek/scp_vow/mt6853",
    },
]
USER_AGENT = "A32x-Nethunter-Kernel-Builder"


def request_bytes(url: str) -> bytes:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    last_error = None
    for attempt in range(5):
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except (ConnectionResetError, HTTPError, URLError) as error:
            last_error = error
            if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                raise
            if attempt < 4:
                delay = 2 ** attempt
                print(f"download retry {attempt + 1}/4 in {delay}s: {url}: {error}")
                time.sleep(delay)
    raise SystemExit(f"download failed after retries: {url}: {last_error}")


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def install_directory(source_root: Path, source: dict) -> list:
    repository = source["repository"]
    commit = source["commit"]
    root_path = source["path"]
    installed = []
    pending = [root_path]

    while pending:
        directory = pending.pop()
        api_url = (
            f"https://api.github.com/repos/{repository}/contents/"
            f"{quote(directory, safe='/')}?ref={commit}"
        )
        entries = json.loads(request_bytes(api_url))
        if not isinstance(entries, list):
            raise SystemExit(f"expected directory listing from {api_url}")

        for entry in entries:
            if entry["type"] == "dir":
                pending.append(entry["path"])
                continue
            if entry["type"] != "file":
                raise SystemExit(
                    f"unsupported {entry['type']} entry in pinned source: {entry['path']}"
                )

            data = request_bytes(entry["download_url"])
            actual_sha = git_blob_sha(data)
            if actual_sha != entry["sha"]:
                raise SystemExit(
                    f"integrity failure for {entry['path']}: "
                    f"expected {entry['sha']}, got {actual_sha}"
                )
            target = source_root / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            installed.append({
                "path": entry["path"],
                "bytes": len(data),
                "git_blob_sha": actual_sha,
                "url": entry["html_url"],
            })

    return sorted(installed, key=lambda item: item["path"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()

    source_results = []
    for source in SOURCES:
        source_results.append({
            **source,
            "license_context": "published Linux kernel GPL source",
            "installed": install_directory(args.source_root, source),
        })

    manifest = {
        "sources": source_results,
        "installed_file_count": sum(
            len(source["installed"]) for source in source_results
        ),
        "unavailable_source_symbols": [
            {
                "symbol": "CONFIG_TOUCHSCREEN_MTK_SOLOMON",
                "expected_path": "drivers/input/touchscreen/mediatek/SOLOMON",
                "reason": (
                    "MediaTek Kconfig/Makefile references the directory, but the "
                    "implementation is absent from published MT6853/MTK 4.14 GPL trees."
                ),
            },
            {
                "symbol": "CONFIG_TOUCHSCREEN_MTK_GSLX680",
                "expected_path": "drivers/input/touchscreen/mediatek/gslX680/mt6853",
                "reason": (
                    "The published driver wrapper selects a platform directory, "
                    "but no MT6853 implementation is present in indexed GPL trees."
                ),
            },
            {
                "symbol": "CONFIG_MTK_PMIC_CHIP_MT6355",
                "expected_path": "drivers/misc/mediatek/accdet/mt6355",
                "reason": (
                    "The vendor Kbuild references this PMIC accdet subtree, "
                    "but no implementation is present in indexed MTK GPL trees."
                ),
            },
            {
                "symbol": "CONFIG_SND_SOC_MTK_SCP_SMARTPA",
                "expected_path": "sound/soc/mediatek/scp_spk/mt6853",
                "reason": (
                    "The smart-PA wrapper requires an MT6853 platform subtree "
                    "that is absent from indexed MT6853 GPL releases."
                ),
            },
            {
                "symbol": "CONFIG_MTK_LASTBUS_INTERFACE",
                "expected_path": "drivers/misc/mediatek/debug_latch/lastbus/mt6853",
                "reason": (
                    "The lastbus wrapper requires an MT6853 platform subtree "
                    "that is absent from indexed MT6853 GPL releases."
                ),
            },
            {
                "symbol": "CONFIG_MTK_EMI",
                "expected_path": "drivers/misc/mediatek/emi/mt6853",
                "reason": (
                    "The EMI wrapper requires an MT6853 platform subtree that "
                    "is absent from indexed MT6853 and Samsung A32 GPL trees."
                ),
            },
            {
                "symbol": "CONFIG_MTK_EMI_MPU",
                "expected_path": "drivers/misc/mediatek/emi_mpu/mt6853",
                "reason": (
                    "The EMI MPU wrapper requires an MT6853 platform subtree "
                    "that is absent from indexed MT6853 and Samsung A32 GPL trees."
                ),
            },
        ],
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
