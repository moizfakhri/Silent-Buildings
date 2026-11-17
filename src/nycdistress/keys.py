"""Key-building helpers. HPD violations ship block/lot but no BBL column."""


def make_bbl(boro, block, lot):
    """Borough (1-5), tax block, tax lot -> 10 digit BBL string, or None if any part is unusable."""
    try:
        b, bl, lt = int(str(boro).strip()), int(str(block).strip()), int(str(lot).strip())
    except (ValueError, TypeError):
        return None
    if not (1 <= b <= 5) or bl < 0 or lt < 0 or bl > 99999 or lt > 9999:
        return None
    return f"{b}{bl:05d}{lt:04d}"
