import pytest

from image_mcp.models import (
    ALLOWED_SIZES,
    DEFAULT_ALIAS,
    DEFAULT_SIZE,
    MODELS,
    choose_alias,
    cost_for,
    model_id,
    resolve_alias,
    resolve_size,
)


def test_choose_alias_dashboard_pref_always_wins():
    assert choose_alias(requested="flash", pref="pro") == "pro"
    assert choose_alias(requested="pro", pref="flash") == "flash"
    assert choose_alias(requested=None, pref="pro") == "pro"


def test_choose_alias_without_pref():
    assert choose_alias(requested="pro", pref=None) == "pro"
    assert choose_alias(requested=None, pref=None) == DEFAULT_ALIAS


def test_registry_shape():
    assert DEFAULT_ALIAS in MODELS
    assert set(MODELS) == {"flash", "pro"}


def test_resolve_alias_accepts_aliases_ids_and_doc_names():
    assert resolve_alias("flash") == "flash"
    assert resolve_alias("pro") == "pro"
    assert resolve_alias("gemini-3.1-flash-image-preview") == "flash"
    assert resolve_alias("gemini-3-pro-image-preview") == "pro"
    # The doc-page names (without the -preview suffix) work too.
    assert resolve_alias("gemini-3.1-flash-image") == "flash"
    assert resolve_alias("gemini-3-pro-image") == "pro"
    assert resolve_alias("  PRO  ") == "pro"


def test_resolve_alias_none_means_no_preference():
    assert resolve_alias(None) is None
    assert resolve_alias("") is None
    assert resolve_alias("   ") is None


def test_resolve_alias_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_alias("dall-e-3")


def test_model_id_env_override(monkeypatch):
    monkeypatch.delenv("IMG_MODEL_FLASH", raising=False)
    assert model_id("flash") == "gemini-3.1-flash-image-preview"
    monkeypatch.setenv("IMG_MODEL_FLASH", "gemini-4-flash-image")
    assert model_id("flash") == "gemini-4-flash-image"
    assert resolve_alias("gemini-4-flash-image") == "flash"


def test_cost_grid_defaults():
    assert cost_for("flash") == 0.067  # default size is 1K
    assert cost_for("flash", "2K") == 0.101
    assert cost_for("flash", "4K") == 0.151
    assert cost_for("pro", "1K") == 0.134
    assert cost_for("pro", "2K") == 0.134
    assert cost_for("pro", "4K") == 0.24
    # Every alias prices every allowed size.
    for alias in MODELS:
        for size in ALLOWED_SIZES:
            assert cost_for(alias, size) > 0


def test_cost_env_override(monkeypatch):
    monkeypatch.setenv("IMG_COST_PRO_4K", "0.3")
    assert cost_for("pro", "4K") == 0.3
    assert cost_for("pro", "1K") == 0.134  # other sizes untouched
    monkeypatch.setenv("IMG_COST_PRO_4K", "not-a-number")
    assert cost_for("pro", "4K") == 0.24


def test_resolve_size():
    assert resolve_size(None) == DEFAULT_SIZE
    assert resolve_size("") == DEFAULT_SIZE
    assert resolve_size("1K") == "1K"
    assert resolve_size("2k") == "2K"
    assert resolve_size(" 4K ") == "4K"
    with pytest.raises(ValueError, match="Unknown image_size"):
        resolve_size("8K")
    with pytest.raises(ValueError, match="Unknown image_size"):
        resolve_size("1024")
