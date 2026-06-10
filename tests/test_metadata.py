from image_mcp.metadata import load_all_meta, load_meta, save_meta, summarize_by_user
from image_mcp.storage import save_image


def _gen(tmp_path, email, prompt, cost=0.039):
    name = save_image(b"png", tmp_path)
    save_meta(
        tmp_path, name, email=email, prompt=prompt,
        aspect_ratio="1:1", cost=cost, model="test-model", model_alias="flash",
    )
    return name


def test_save_and_load_roundtrip(tmp_path):
    name = _gen(tmp_path, "a@x.com", "a red cat")
    metas = load_all_meta(tmp_path)
    assert len(metas) == 1
    assert metas[0]["name"] == name
    assert metas[0]["email"] == "a@x.com"
    assert metas[0]["prompt"] == "a red cat"
    assert metas[0]["cost"] == 0.039
    assert metas[0]["model_alias"] == "flash"
    assert metas[0]["created"]


def test_load_skips_foreign_and_broken_files(tmp_path):
    _gen(tmp_path, "a@x.com", "ok")
    (tmp_path / "notes.json").write_text("{}")  # foreign name: skipped
    (tmp_path / ("0" * 32 + ".json")).write_text("{broken")  # bad JSON: skipped
    assert len(load_all_meta(tmp_path)) == 1


def test_load_missing_dir(tmp_path):
    assert load_all_meta(tmp_path / "nope") == []


def test_load_meta_by_name(tmp_path):
    name = _gen(tmp_path, "a@x.com", "a red cat", cost=0.067)
    meta = load_meta(tmp_path, name)
    assert meta is not None
    assert meta["prompt"] == "a red cat"
    assert meta["email"] == "a@x.com"
    # A full URL's trailing segment is the caller's job to strip; the bare
    # name is what we accept here.
    assert load_meta(tmp_path, "0" * 32 + ".png") is None
    assert load_meta(tmp_path, "not-a-name") is None


def test_summarize_groups_and_sorts_by_cost(tmp_path):
    _gen(tmp_path, "small@x.com", "one", cost=0.01)
    _gen(tmp_path, "big@x.com", "two", cost=0.05)
    _gen(tmp_path, "big@x.com", "three", cost=0.05)
    summary = summarize_by_user(load_all_meta(tmp_path))
    assert [email for email, _ in summary] == ["big@x.com", "small@x.com"]
    big = summary[0][1]
    assert big["count"] == 2
    assert abs(big["cost"] - 0.10) < 1e-9
    assert len(big["images"]) == 2
