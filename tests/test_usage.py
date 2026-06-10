from image_mcp.usage import build_help


def test_help_mentions_every_parameter():
    text = build_help("https://images.example.com")
    for param in ("prompt", "model", "image_size", "aspect_ratio", "reference_images"):
        assert param in text


def test_help_includes_models_prices_and_values():
    text = build_help("https://images.example.com/")
    assert "gemini-3.1-flash-image-preview" in text
    assert "gemini-3-pro-image-preview" in text
    assert "$0.067" in text and "$0.134" in text and "$0.240" in text
    assert "1K, 2K, 4K" in text
    assert "21:9" in text


def test_help_uses_public_url_without_trailing_slash():
    text = build_help("https://images.example.com/")
    assert "https://images.example.com/ui" in text
    assert "https://images.example.com//" not in text


def test_help_reflects_env_price_override(monkeypatch):
    monkeypatch.setenv("IMG_COST_PRO_4K", "0.5")
    assert "$0.500" in build_help("https://images.example.com")
