import pytest

from image_mcp.prefs import get_default_model, set_default_model


def test_unset_returns_none(tmp_path):
    assert get_default_model(tmp_path, "a@x.com") is None


def test_set_then_get_roundtrip(tmp_path):
    set_default_model(tmp_path, "a@x.com", "pro")
    assert get_default_model(tmp_path, "a@x.com") == "pro"
    assert get_default_model(tmp_path, "other@x.com") is None
    # Case-insensitive on the email, like the allow-list.
    assert get_default_model(tmp_path, "A@X.com") == "pro"


def test_overwrite_and_multiple_users(tmp_path):
    set_default_model(tmp_path, "a@x.com", "pro")
    set_default_model(tmp_path, "b@x.com", "flash")
    set_default_model(tmp_path, "a@x.com", "flash")
    assert get_default_model(tmp_path, "a@x.com") == "flash"
    assert get_default_model(tmp_path, "b@x.com") == "flash"


def test_rejects_unknown_alias(tmp_path):
    with pytest.raises(ValueError):
        set_default_model(tmp_path, "a@x.com", "dall-e")


def test_corrupt_file_is_tolerated(tmp_path):
    (tmp_path / "prefs.json").write_text("{broken")
    assert get_default_model(tmp_path, "a@x.com") is None
    set_default_model(tmp_path, "a@x.com", "pro")
    assert get_default_model(tmp_path, "a@x.com") == "pro"
