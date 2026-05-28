# TEST PATTERN: contract + effect — daily-task 图标"统一大小"契约
# USE WHEN: 改 _get_or_create_processed_attachment / normalize_subject_frame /
#           cutout_local → cache 链路时,验两条 backend 出来的 cache 形状一致
# WHY: 5.28 南非醉茄 bug — 端侧 cutout_local 路径没过 normalize_subject_frame,
#      cache 出来保留原 aspect ratio(1280×1280 + subject ratio 44%),跟其他图
#      (1024×1024 + subject ratio 83%)对不齐 → 渲染时大小不一致。
#      根因:normalize 之前只在 baidu_cutout_image 内部调,端侧 PNG 直接 write_bytes。
#      契约:任何 cutout backend 出来的 cache 必为 1024×1024 + subject 长边 ≈ 870 px。

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

# server 模块在 import 时跑很多 OS 路径解析,放 sys.path 后再 import
import cutout  # noqa: E402
import server  # noqa: E402


# ─── 辅助:造一张瘦长/方/矮胖的 RGBA PNG(模拟抠图 backend 的输出)──────

def _make_rgba_png(canvas_w: int, canvas_h: int,
                   subject_w: int, subject_h: int) -> bytes:
    """中心位置画一块不透明矩形(模拟主体),其余透明。"""
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    ox = (canvas_w - subject_w) // 2
    oy = (canvas_h - subject_h) // 2
    sub = Image.new("RGBA", (subject_w, subject_h), (180, 90, 50, 255))
    img.paste(sub, (ox, oy), sub)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── T1 · contract: normalize 输出固定 1024×1024 方形 ─────────────────

@pytest.mark.parametrize("cw,ch,sw,sh", [
    (1280, 1280, 573, 1100),  # 瘦长瓶(南非醉茄 KSM-66 原始 ratio 44%)
    (800,  600,  500, 400),   # 矮胖罐
    (1024, 1024, 858, 858),   # 已经接近目标的方块
    (200,  200,  100, 100),   # 小图(需要上采样)
])
def test_normalize_outputs_1024_square(cw, ch, sw, sh):
    png = _make_rgba_png(cw, ch, sw, sh)
    out_bytes = cutout.normalize_subject_frame(png)
    out_img = Image.open(io.BytesIO(out_bytes))
    assert out_img.size == (1024, 1024), \
        f"input {cw}x{ch} subject {sw}x{sh} → expected 1024x1024, got {out_img.size}"
    assert out_img.mode == "RGBA"


# ─── T2 · contract: subject 长边 ≈ 1024 × (1 − 2×0.08) = 870 px ──────

@pytest.mark.parametrize("cw,ch,sw,sh", [
    (1280, 1280, 573, 1100),
    (800,  600,  500, 400),
    (200,  200,  150, 80),
])
def test_normalize_subject_long_edge_consistent(cw, ch, sw, sh):
    """无论输入 aspect ratio,输出主体长边都在 ~870 px ± 容差。
    这是"视觉大小统一"的本质 — UI 渲染 36×36 时,主体占同样比例。
    """
    png = _make_rgba_png(cw, ch, sw, sh)
    out_bytes = cutout.normalize_subject_frame(png)
    out_img = Image.open(io.BytesIO(out_bytes)).convert("RGBA")
    bbox = out_img.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
    assert bbox is not None
    long_edge = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    # padding_ratio=0.08, target=1024 → subject_target = 1024 × 0.84 = 860
    # 容差 ±20 px 给 round / paste 精度
    assert 840 <= long_edge <= 880, \
        f"long_edge={long_edge}, expected ~860 (1024×0.84)"


# ─── T3 · effect: 端侧路径 cache 也是 1024×1024(回归测,锁 5.28 bug)─

def test_local_cutout_path_normalizes_cache(tmp_path, monkeypatch):
    """模拟 cutout_local 返回非标准尺寸 PNG(模拟 macOS Subject Lift 出来的原 ratio),
    跑 _get_or_create_processed_attachment,验 cache 文件是 1024×1024。
    bug 之前:这里会 assert 失败 — cache 是 800×600 原样写入。
    """
    # 建一个假的 attachment 目录结构
    monkeypatch.setattr(server, "ATTACHMENTS_DIR", tmp_path / "attachments")
    bucket = tmp_path / "attachments" / "test-bucket"
    bucket.mkdir(parents=True)
    src = bucket / "ksm66.jpg"
    src.write_bytes(b"fake jpg content")  # 内容无关,只要 file exists

    # mock cutout_local 返回瘦长 RGBA PNG(模拟 Subject Lift 出来的原 aspect)
    fake_cutout_png = _make_rgba_png(800, 600, 500, 400)

    # mock load_config 避免触发真 cfg 加载
    monkeypatch.setattr(server, "load_config", lambda: {})

    import cutout_local
    with patch.object(cutout_local, "cutout_local", return_value=fake_cutout_png):
        path, err = server._get_or_create_processed_attachment(
            "/attachments/test-bucket/ksm66.jpg"
        )

    assert err is None, f"unexpected err: {err}"
    assert path.exists()
    out = Image.open(path)
    assert out.size == (1024, 1024), \
        f"端侧路径 cache 应被 normalize 成 1024x1024,实际 {out.size}"


# ─── T4 · contract: bbox 不变(主体不被裁掉)──────────────────────────

def test_normalize_preserves_subject_no_crop():
    """主体应整体保留(可缩放可居中,但不能被裁)。"""
    png = _make_rgba_png(1280, 1280, 573, 1100)
    out = Image.open(io.BytesIO(cutout.normalize_subject_frame(png))).convert("RGBA")
    bbox = out.split()[3].point(lambda v: 255 if v > 8 else 0).getbbox()
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # 原 aspect 1100:573 ≈ 1.92,缩放后应保留
    ratio = bh / bw
    assert 1.85 <= ratio <= 1.99, f"aspect ratio drifted: bw={bw} bh={bh}"
