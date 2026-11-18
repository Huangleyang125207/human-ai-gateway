import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vision_tools  # noqa: E402


class _Completions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def _wire(monkeypatch, cfg, completions):
    factory_calls = []
    monkeypatch.setattr(vision_tools, "_LOAD_CONFIG", lambda: cfg)
    monkeypatch.setattr(
        vision_tools,
        "_GET_PROFILE",
        lambda *_: cfg if cfg.get("api_key") else None,
    )
    monkeypatch.setattr(vision_tools, "_REPORT_FAILURE", lambda *a, **k: None)
    monkeypatch.setattr(vision_tools, "_LOGGER", lambda: SimpleNamespace(warning=lambda *a: None))
    monkeypatch.setattr(
        vision_tools,
        "_OPENAI_FACTORY",
        lambda **kwargs: factory_calls.append(kwargs)
        or SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(
        vision_tools,
        "_GET_CLIENT",
        lambda profile: vision_tools._OPENAI_FACTORY(
            api_key=profile["api_key"], base_url=profile["base_url"], timeout=120.0, max_retries=1
        ),
    )
    monkeypatch.setattr(vision_tools, "_compress_for_vision", lambda _: b"jpeg")
    return factory_calls


def test_deepseek_vision_uses_primary_key_and_experimental_model(monkeypatch, tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"png")
    completions = _Completions(json.dumps({"kind": "food", "description": "一碗面"}))
    factory_calls = _wire(
        monkeypatch,
        {"api_key": "sk-deepseek", "base_url": "https://api.deepseek.com/v1"},
        completions,
    )

    result = vision_tools._deepseek_classify_image(image)

    assert result == {"ok": True, "kind": "food", "description": "一碗面"}
    assert factory_calls[0]["api_key"] == "sk-deepseek"
    assert factory_calls[0]["base_url"] == "https://api.deepseek.com/v1"
    call = completions.calls[0]
    assert call["model"] == "deepseek-v4-flash-vision-exp"
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "ocr_text" in call["messages"][0]["content"][0]["text"]
    assert call["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_deepseek_vision_never_falls_back_to_dashscope_key(monkeypatch, tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"png")
    completions = _Completions("{}")
    factory_calls = _wire(monkeypatch, {"dashscope_api_key": "sk-legacy"}, completions)

    result = vision_tools._deepseek_classify_image(image)

    assert result["error"] == "no_deepseek_key"
    assert factory_calls == []


def test_deepseek_vision_does_not_send_key_to_a_custom_provider(monkeypatch, tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"png")
    completions = _Completions("{}")
    factory_calls = _wire(
        monkeypatch,
        {"api_key": "sk-deepseek", "base_url": "https://example.invalid/v1"},
        completions,
    )

    result = vision_tools._deepseek_classify_image(image)

    assert result["error"] == "vision_provider_incompatible"
    assert factory_calls == []
