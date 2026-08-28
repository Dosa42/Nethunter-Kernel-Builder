#!/usr/bin/env python3
from pathlib import Path
import argparse, shutil


def append_once(path: Path, text: str):
    s = path.read_text()
    if text.strip() not in s:
        path.write_text(s.rstrip() + "\n" + text.rstrip() + "\n")


def insert_once(path: Path, marker: str, block: str):
    s = path.read_text()
    if block.strip() in s:
        return
    if marker not in s:
        raise RuntimeError(f"marker not found in {path}: {marker!r}")
    path.write_text(s.replace(marker, block.rstrip() + "\n\n" + marker, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", required=True, type=Path)
    ap.add_argument("--payload-root", required=True, type=Path)
    args = ap.parse_args()
    src = args.source_root.resolve()
    payload = args.payload_root.resolve()

    dst = src / "drivers/misc/codex_responses"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("codex_responses_hw.c", "Kconfig", "Makefile"):
        shutil.copy2(payload / name, dst / name)

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

    print("Codex Responses kernel bridge installed")

if __name__ == "__main__":
    main()
