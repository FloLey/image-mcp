from image_mcp.storage import delete_image, is_safe_image_name, load_image, save_image
from image_mcp.metadata import save_meta


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


def test_delete_removes_png_and_sidecar(tmp_path):
    name = save_image(b"png", tmp_path)
    save_meta(
        tmp_path, name, email="a@x.com", prompt="p",
        aspect_ratio="1:1", cost=0.067, model="m", model_alias="flash",
    )
    sidecar = tmp_path / f"{name.rsplit('.', 1)[0]}.json"
    assert sidecar.is_file()
    assert delete_image(name, tmp_path) is True
    assert load_image(name, tmp_path) is None
    assert not sidecar.is_file()


def test_delete_missing_or_unsafe_returns_false(tmp_path):
    assert delete_image("0" * 32 + ".png", tmp_path) is False
    assert delete_image("../etc/passwd", tmp_path) is False


def test_delete_without_sidecar_is_ok(tmp_path):
    name = save_image(b"png", tmp_path)
    assert delete_image(name, tmp_path) is True
    assert load_image(name, tmp_path) is None
