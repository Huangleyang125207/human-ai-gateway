# test_updater_step_contract.py — updater://progress step 字符串状态机 Rust↔JS 契约对拍。
# 清册 08 危险点③:lib.rs emit 的 step 枚举与 update-banner.js 处理的枚举靠裸字符串耦合,
# 此前零自动化(py sidecar 端另有 test_updater_report.py;这里补 Rust↔JS 段)。
# TEST PATTERN: contract — cross-language string-enum parity via source grep
# USE WHEN: 两种语言经事件字符串耦合、无共享常量文件时锁枚举集合
# COPY THIS: 换 RUST_SRC/JS_SRC 路径与提取正则
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUST_SRC = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
JS_SRC = (ROOT / "shared" / "update-banner.js").read_text(encoding="utf-8")

# lib.rs 侧:emit payload 里的 step 值(json!({"step": "xxx"...}) 形态)
RUST_STEPS = set(re.findall(r'"step"\s*:\s*"([a-z_]+)"', RUST_SRC)) | set(
    re.findall(r'step\s*:\s*"([a-z_]+)"', RUST_SRC)
)
# sidecar SSE 段(迁移进度,py 发、banner 收;不经 lib.rs)— 契约常量,变更需同步三处
SIDECAR_STEPS = {"migrating", "migrated"}
# banner 侧:字符串比较/分支里出现的 step 值(排除 UI 状态词)
JS_TOKENS = set(re.findall(r'["\']([a-z_]+)["\']', JS_SRC))
UI_STATES = {"active", "pending", "done", "step"}  # banner 自己的进度点样式态,非协议枚举


def test_banner_handles_every_rust_step():
    """lib.rs 会 emit 的每个 step,banner 必须认识 — 少一个 = 该阶段 UI 静默。"""
    rust = RUST_STEPS - {"step"}
    assert rust, "提取失败:lib.rs 里没解析到 step 枚举(正则或源文件变了)"
    missing = rust - JS_TOKENS
    assert not missing, f"update-banner.js 不认识 lib.rs 的 step: {sorted(missing)}"


def test_expected_enum_frozen():
    """枚举全集快照(6 Rust + 2 sidecar)。有意增删 step 时同步改这里 — 防无声漂移。"""
    rust = RUST_STEPS - {"step"}
    assert rust == {"found", "download", "install", "ready_restart", "error", "uptodate"}, (
        f"lib.rs step 枚举漂移: {sorted(rust)}"
    )
    assert SIDECAR_STEPS <= JS_TOKENS, "banner 丢了 sidecar 迁移步骤 migrating/migrated 的处理"


def test_no_unknown_protocol_steps_in_banner():
    """banner 处理的协议步骤不能超出 Rust+sidecar 全集(多出的 = 死分支或拼写漂移)。

    只检查出现在 step 语境(与 'step' 同行)的 token,避免误伤普通字符串。"""
    step_lines = [l for l in JS_SRC.splitlines() if "step" in l]
    tokens = set(re.findall(r'["\']([a-z_]+)["\']', "\n".join(step_lines))) - UI_STATES
    known = (RUST_STEPS - {"step"}) | SIDECAR_STEPS
    unknown = {t for t in tokens if t in known or t in {"found", "uptodate"}} - known
    assert not unknown, f"banner 出现未知协议 step: {sorted(unknown)}"
