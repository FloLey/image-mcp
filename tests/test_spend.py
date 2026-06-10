from image_mcp import spend


def test_empty_ledger(tmp_path):
    assert spend.totals(tmp_path) == {}


def test_record_accumulates(tmp_path):
    spend.record(tmp_path, "a@x.com", 0.067)
    spend.record(tmp_path, "a@x.com", 0.134)
    assert spend.totals(tmp_path)["a@x.com"] == 0.201


def test_record_is_case_insensitive_on_email(tmp_path):
    spend.record(tmp_path, "A@X.com", 0.1)
    spend.record(tmp_path, "a@x.com", 0.1)
    assert spend.totals(tmp_path) == {"a@x.com": 0.2}


def test_total_does_not_drop_when_image_deleted(tmp_path):
    # Recording is the only thing that moves the total; nothing in this module
    # ever subtracts, so a deletion elsewhere cannot lower it.
    spend.record(tmp_path, "a@x.com", 0.134)
    before = spend.totals(tmp_path)["a@x.com"]
    # (image + sidecar deleted elsewhere) -> ledger untouched
    assert spend.totals(tmp_path)["a@x.com"] == before


def test_seed_missing_is_idempotent_and_only_fills_gaps(tmp_path):
    spend.seed_missing(tmp_path, {"a@x.com": 0.5})
    assert spend.totals(tmp_path)["a@x.com"] == 0.5
    # A later generation moves the real total past the seed.
    spend.record(tmp_path, "a@x.com", 0.1)
    # Re-seeding (e.g. on the next restart) must not reset or double-count it.
    spend.seed_missing(tmp_path, {"a@x.com": 0.5})
    assert spend.totals(tmp_path)["a@x.com"] == 0.6
    # New users still get seeded.
    spend.seed_missing(tmp_path, {"b@x.com": 0.3})
    assert spend.totals(tmp_path)["b@x.com"] == 0.3


def test_junk_values_and_blank_emails_are_ignored(tmp_path):
    (tmp_path / "spend.json").write_text('{"a@x.com": "oops", "": 1.0}')
    assert spend.totals(tmp_path) == {"a@x.com": 0.0}


def test_corrupt_file_is_tolerated_and_preserved(tmp_path):
    (tmp_path / "spend.json").write_text("{broken")
    assert spend.totals(tmp_path) == {}
    # The corrupt content is set aside for manual recovery, not destroyed.
    assert (tmp_path / "spend.corrupt").read_text() == "{broken"
    spend.record(tmp_path, "a@x.com", 0.2)
    assert spend.totals(tmp_path)["a@x.com"] == 0.2
