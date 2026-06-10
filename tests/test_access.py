from image_mcp.access import is_allowed_email, parse_allowed_emails


def test_parse_normalizes_and_drops_empties():
    allowed = parse_allowed_emails(" A@x.com, b@Y.com ,, ")
    assert allowed == frozenset({"a@x.com", "b@y.com"})


def test_parse_empty_inputs():
    assert parse_allowed_emails(None) == frozenset()
    assert parse_allowed_emails("") == frozenset()
    assert parse_allowed_emails(" , ") == frozenset()


def test_allowed_email_case_insensitive():
    allowed = parse_allowed_emails("friend@gmail.com")
    assert is_allowed_email("Friend@Gmail.com", allowed)
    assert is_allowed_email(" friend@gmail.com ", allowed)


def test_denies_unknown_email():
    allowed = parse_allowed_emails("friend@gmail.com")
    assert not is_allowed_email("stranger@gmail.com", allowed)


def test_fails_closed_on_missing_claim_or_empty_list():
    allowed = parse_allowed_emails("friend@gmail.com")
    assert not is_allowed_email(None, allowed)
    assert not is_allowed_email("", allowed)
    assert not is_allowed_email(123, allowed)
    # Empty allow-list denies everyone, even an empty claim.
    assert not is_allowed_email("", frozenset())
    assert not is_allowed_email("friend@gmail.com", frozenset())
