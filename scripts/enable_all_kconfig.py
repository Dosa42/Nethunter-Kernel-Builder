#!/usr/bin/env python3
"""Request every disabled boolean/tristate Kconfig symbol as built-in."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DISABLED_RE = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")
ENABLED_RE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(?:y|m)$")


def disabled(path: Path) -> list[str]:
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = DISABLED_RE.match(line)
        if match:
            result.append(match.group(1))
    return result


def active(path: Path) -> set[str]:
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ENABLED_RE.match(line)
        if match:
            result.add(match.group(1))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--fragment", type=Path)
    parser.add_argument("--requested", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    current_disabled = disabled(args.config)

    if args.fragment:
        args.fragment.write_text(
            "\n".join(f"{symbol}=y" for symbol in current_disabled) + "\n",
            encoding="utf-8",
        )
        if args.requested:
            args.requested.write_text(
                "\n".join(current_disabled) + "\n", encoding="utf-8"
            )
        print(f"requested {len(current_disabled)} disabled symbols as =y")
        return 0

    if not args.requested or not args.json_output:
        parser.error("verification requires --requested and --json-output")

    requested = [
        line.strip()
        for line in args.requested.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    enabled = active(args.config)
    remaining = [symbol for symbol in requested if symbol not in enabled]
    report = {
        "requested_count": len(requested),
        "enabled_count": len(requested) - len(remaining),
        "remaining_disabled_count": len(remaining),
        "remaining_disabled": remaining,
        "all_requested_enabled": not remaining,
    }
    args.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
