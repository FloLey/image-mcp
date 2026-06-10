from image_mcp.storage import is_safe_image_name, load_image, save_image


def test_save_then_load_roundtrip(tmp_path):
    name = save_image(b"png-bytes", tmp_path)
    assert is_safe_image_name(name)
    assert (tmp_path / name).read_bytes() == b"png-bytes"
    assert load_image(name, tmp_path) == b"png-bytes"


def test_names_are_unique(tmp_path):
    names = {save_image(b"x", tmp_path) for _ in range(5)}
    assert len(names) == 5


def test_load_rejects_unsafe_names(tmp_path):
    (tmp_path / "secret.txt").write_text("nope")
    for bad in (
        "../etc/passwd",
        "secret.txt",
        "a/b.png",
        ".png",
        "ABCDEF00112233445566778899aabbcc.png",  # uppercase hex
        "0" * 31 + ".png",  # too short
    ):
        assert load_image(bad, tmp_path) is None


def test_load_missing_file_returns_none(tmp_path):
    assert load_image("0" * 32 + ".png", tmp_path) is None
