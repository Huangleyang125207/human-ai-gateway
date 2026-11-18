#!/usr/bin/env python3
"""Generate PC-owned tool schemas/effects for RN, or verify freshness."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parent.parent
RN_SERVICES = GATEWAY_DIR.parent / "gateway-rn" / "services"
FINGERPRINT_OUT = GATEWAY_DIR / "docs" / "contracts" / "tool-contracts.sha256"
sys.path.insert(0, str(GATEWAY_DIR))

from action_policy import TOOL_EFFECTS  # noqa: E402
from tool_specs import TOOLS  # noqa: E402


def _payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def outputs() -> dict[Path, str]:
    specs = _payload(TOOLS)
    return {
        RN_SERVICES / "toolSpecs.json": specs,
        RN_SERVICES / "__tests__" / "golden" / "pc-tool-specs.json": specs,
        RN_SERVICES / "toolEffects.json": _payload(TOOL_EFFECTS),
    }


def fingerprint(payloads: dict[Path, str]) -> str:
    stable = "".join(
        name + "\0" + payloads[path]
        for name, path in sorted((path.name, path) for path in payloads)
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    rn_outputs = outputs()
    expected_outputs = {FINGERPRINT_OUT: fingerprint(rn_outputs)}
    if RN_SERVICES.exists():
        expected_outputs.update(rn_outputs)
    for path, payload in expected_outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != payload:
                stale.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print("stale generated tool contracts:\n" + "\n".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
