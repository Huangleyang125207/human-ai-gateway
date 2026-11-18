"""Tag vocabulary metadata and progressive Harness disclosure.

The aggregate Markdown remains human-editable.  This module owns only the
small semantic block returned when an AI write proposes an unknown tag;
derived journal rows never enter the prompt or disclosure.
"""

import json
import re


META_LABELS = {
    "description": "说明",
    "scope": "适用范围",
    "avoid": "避免用于",
}
MAX_TAGS = 80
MAX_CONTEXT_CHARS = 8000


def metadata_from_section(section: dict) -> dict:
    return {
        "description": str(section.get("description") or "").strip(),
        "scope": str(section.get("scope") or "").strip(),
        "avoid": str(section.get("avoid") or "").strip(),
    }


def missing_metadata_tags(sections: list[dict]) -> list[str]:
    return sorted(
        section["tag"]
        for section in sections
        if not metadata_from_section(section)["description"]
        or not metadata_from_section(section)["scope"]
    )


def render_tag_vocabulary_context(sections: list[dict]) -> str:
    """Render stable name/meaning rows; omit dates, counts and usage samples."""
    rows = []
    for section in sorted(sections, key=lambda item: item["tag"])[:MAX_TAGS]:
        meta = metadata_from_section(section)
        meaning = meta["description"] or "待补充"
        scope = meta["scope"] or "按标签名称的通常含义使用"
        avoid = f"；避免：{meta['avoid']}" if meta["avoid"] else ""
        rows.append(f"- #{section['tag']}｜{meaning}｜适用：{scope}{avoid}")
    if not rows:
        return ""
    header = (
        "=== TAG_VOCABULARY（受控标签词表）===\n"
        "写日记时优先复用下列现有标签；选择语义最贴切且最具体的一项。"
        "只有没有任何标签适用时才创建新标签，禁止创建近义重复标签。\n"
    )
    return (header + "\n".join(rows))[:MAX_CONTEXT_CHARS]


def parent_tags(values) -> list[str]:
    """Normalize candidate tag tokens to stable, unique parent names."""
    found = []
    for value in values or []:
        raw = str(value or "").strip().lstrip("#").strip()
        parent = raw.split("/", 1)[0].strip()
        if parent and parent not in found:
            found.append(parent)
    return found


def h2_parent_tags(markdown: str) -> list[str]:
    """Extract parent tags only from H2 headings that a patch would persist."""
    values = []
    for line in str(markdown or "").splitlines():
        if not line.startswith("## "):
            continue
        values.extend(re.findall(r"#([A-Za-z0-9_\-/一-鿿]+)", line))
    return parent_tags(values)


def build_tag_disclosure(values, sections: list[dict]):
    """Return a fail-closed tool result only when candidate parents are unknown."""
    requested = parent_tags(values)
    registered = {str(section.get("tag") or "").strip() for section in sections}
    unknown = [tag for tag in requested if tag not in registered]
    if not unknown:
        return None
    vocabulary = render_tag_vocabulary_context(sections)
    return {
        "ok": False,
        "error": "tag_disclosure_required",
        "requested_tags": unknown,
        "tag_vocabulary": vocabulary or "（当前没有已注册标签）",
        "next_step": (
            "本次日记尚未写入。请先从 tag_vocabulary 复用合适标签；"
            "若确无合适项，调用 manage_tag_aggregate(action='register', tag='新标签')，"
            "成功后重试原写入。"
        ),
    }


def build_annotation_prompt(tag: str, usage_titles: list[str]) -> str:
    samples = "\n".join(f"- {title[:160]}" for title in usage_titles[:8]) or "- （暂无使用样例）"
    return (
        "你在维护一个人的日记受控标签词表。请定义标签，帮助后续 AI 复用旧标签、避免近义重复。\n"
        f"标签：#{tag}\n使用标题样例：\n{samples}\n\n"
        "返回严格 JSON 对象，不要 Markdown："
        '{"description":"一句话说明","scope":"适合记录哪些事情","avoid":"不适合哪些近义场景"}'
        "。每个值不超过80个中文字符；不要推断用户身份或敏感属性。"
    )


def parse_annotation_response(raw: str) -> dict:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("tag annotation must be a JSON object")
    result = {}
    for key in META_LABELS:
        item = str(value.get(key) or "").strip().replace("\n", " ")
        if key != "avoid" and not item:
            raise ValueError(f"missing tag annotation field: {key}")
        if len(item) > 80:
            raise ValueError(f"tag annotation field too long: {key}")
        result[key] = item
    return result


def apply_tag_metadata(text: str, tag: str, metadata: dict, *, only_if_missing: bool = True) -> str:
    """Replace/insert the owned metadata lines before a section's main table."""
    section_re = re.compile(
        rf"(^##\s+#{re.escape(tag)}\s*$)(.*?)(?=^##\s+#\S+\s*$|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = section_re.search(text)
    if not match:
        raise ValueError(f"unknown tag: {tag}")
    body = match.group(2)
    existing = {}
    for key, label in META_LABELS.items():
        found = re.search(rf"^>?\s*{re.escape(label)}[：:]\s*(.*?)\s*$", body, re.MULTILINE)
        existing[key] = found.group(1).strip() if found else ""
    merged = {
        key: existing[key] if only_if_missing and existing[key] else str(metadata.get(key) or "").strip()
        for key in META_LABELS
    }
    lines = [f"> {META_LABELS[key]}：{merged[key]}" for key in META_LABELS if merged[key]]
    cleaned = body
    for label in META_LABELS.values():
        cleaned = re.sub(rf"^>?\s*{re.escape(label)}[：:].*?\n", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.lstrip("\n")
    replacement = match.group(1) + "\n\n" + "\n".join(lines) + "\n\n" + cleaned
    return text[:match.start()] + replacement + text[match.end():]
