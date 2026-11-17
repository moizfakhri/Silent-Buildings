from nycdistress.keys import make_bbl


def test_make_bbl():
    assert make_bbl("3", "1656", "30") == "3016560030"
    assert make_bbl(2, 3260, 64) == "2032600064"  # matches litigation sample bbl
    assert make_bbl("3", "x", "30") is None
    assert make_bbl("9", "1", "1") is None
