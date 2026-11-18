#!/usr/bin/env python3
"""generate_prompt_contract.py — dump gateway/prompts/*.md + protocol sources into
gateway-rn/services/promptContract.json.

GENERATED FILE NOTICE (mirrors services/toolSpecs.ts header wording):
this script's output (gateway-rn/services/promptContract.json) is a generated file.
Regenerate after ANY change to gateway/prompts/*.md, gateway/protocols/schedule.md,
or the PROTOCOLS dict in gateway/prompt_builder.py by running:

    python3 gateway/scripts/generate_prompt_contract.py

Mirrors the existing toolSpecs.ts generation-chain pattern (see that file's header
comment): PC .md/.py source of truth → this script → generated JSON → RN renders at
runtime → services/__tests__/promptParity.test.ts (contract test) asserts byte parity
against golden/pc-prompt-contract.json.

Only the segments that are byte-identical between PC and RN are dumped here. RN-only
additive/divergent segments (doc-OCR wording, "kind=supplement" step ⓪, the
vision-pre-router opening line, etc. — see gateway-rn/PARITY_HARNESS_2026-07-19.md)
stay hand-written in gateway-rn/services/chatPretext.ts with a comment explaining why.
"""
import ast
import argparse
import hashlib
import json
import sys
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = GATEWAY_DIR / "prompts"
PROTOCOLS_DIR = GATEWAY_DIR / "protocols"
RN_OUT = GATEWAY_DIR.parent / "gateway-rn" / "services" / "promptContract.json"
GOLDEN_OUT = GATEWAY_DIR.parent / "gateway-rn" / "services" / "__tests__" / "golden" / "pc-prompt-contract.json"
FINGERPRINT_OUT = GATEWAY_DIR / "docs" / "contracts" / "prompt-contract.sha256"
sys.path.insert(0, str(GATEWAY_DIR))
from skill_runtime import exported_skills, render_skill_index  # noqa: E402


def _read(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _load_protocols() -> list:
    """PROTOCOLS dict lives in prompt_builder.py as a plain dict literal — extract via
    AST rather than importing the module (avoids pulling in the full server.py import
    chain / fastapi etc. just to run this generator)."""
    src = (GATEWAY_DIR / "prompt_builder.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", None) == "PROTOCOLS":
            d = ast.literal_eval(node.value)
            return [{"name": k, "desc": v} for k, v in d.items()]
    raise RuntimeError("PROTOCOLS dict not found in prompt_builder.py")


def _split_vision_workflow(text: str) -> dict:
    """Split prompts/vision_workflow.md into the byte-identical-with-RN segments.
    Split points are literal anchors present in both PC's f-string source and RN's
    hand-written chatPretext.ts (verified 2026-07-22) — see PARITY_HARNESS for what's
    intentionally NOT included here (doc-OCR special cases, opening tag line, the
    RN-only supplement step ⓪)."""
    i_pin_special = text.index("    特例 · kind=doc + ocr_likely=true:\n      用 patch_journal_block")
    i_ask_start = text.index("\n  ── ask path ──")
    i_special_types = text.index("\n  特殊类型分流(覆盖上面三 path):")
    i_supplement = text.index("\n    kind=supplement")
    i_supplement_step1 = text.index("      ① read_today_schedule")
    return {
        "stepAAndPinGeneric": text[:i_pin_special],
        "askPath": text[i_ask_start:i_special_types],
        "specialTypesAndWaterCup": text[i_special_types:i_supplement],
        # split so RN can splice its own ⓪ step between the header line and ①
        # (see gateway-rn/PARITY_HARNESS_2026-07-19.md "kind=supplement" divergence row)
        "supplementHeader": text[i_supplement:i_supplement_step1],
        "supplementSteps123": text[i_supplement_step1:],
        # discussGeneric intentionally EXCLUDED — RN's discuss-generic text (chatPretext.ts
        # buildVisionHint) matches this span but the doc-special immediately after it is
        # divergent; kept as one hand-written block in TS for readability. PC still reads
        # the un-split prompts/vision_workflow.md directly, so no drift risk on PC side.
    }


def _payload() -> str:
    contract = {
        "_generated_by": "gateway/scripts/generate_prompt_contract.py — DO NOT EDIT BY HAND. "
                          "Regenerate: python3 gateway/scripts/generate_prompt_contract.py",
        "baseline": _read("baseline.md"),
        "protocolIndexHeader": _read("protocol_index_header.md"),
        "protocolIndexFooter": _read("protocol_index_footer.md"),
        "protocols": _load_protocols(),
        "toolCatalog": _read("tool_catalog.md"),
        "journalWriting": _read("journal_writing.md"),
        "scheduleProtocol": (PROTOCOLS_DIR / "schedule.md").read_text(encoding="utf-8"),
        "skillIndex": render_skill_index(),
        "skills": exported_skills(),
        "visionWorkflow": _split_vision_workflow(_read("vision_workflow.md")),
    }
    return json.dumps(contract, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = _payload()
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest() + "\n"
    stale = []
    outputs = [(FINGERPRINT_OUT, fingerprint)]
    # GitHub release CI checks out gateway as a standalone repository. The committed
    # source-output fingerprint remains checkable there; a paired local checkout also
    # verifies the actual RN generated files byte-for-byte.
    if RN_OUT.parent.exists():
        outputs.extend([(RN_OUT, payload), (GOLDEN_OUT, payload)])
    for path, expected in outputs:
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                stale.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print("stale generated prompt contracts:\n" + "\n".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
