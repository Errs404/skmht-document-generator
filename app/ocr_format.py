"""Display casing for OCR-derived human-readable fields only."""

import re


HUMAN_READABLE_FIELDS = frozenset({
    "nama", "pemegang_hak", "tempat_lahir", "pekerjaan", "alamat",
    "dusun", "kel_desa", "desa", "kecamatan", "kabupaten", "provinsi",
})

# Keep common address/occupation acronyms intact, not arbitrary uppercase names.
_ACRONYMS = frozenset({"RT", "RW", "DKI", "DIY", "PNS", "TNI", "POLRI",
                         "BUMN", "BUMD", "PT", "CV", "WNI", "WNA"})


def format_field(key: str, value: str) -> str:
    """Never change identifier/date fields or digit-bearing tokens."""
    if key in ("nama", "pemegang_hak"):
        return value.upper()
    if key not in HUMAN_READABLE_FIELDS:
        return value

    def word(match):
        token = match.group()
        if any(char.isdigit() for char in token):
            return token
        if token.upper() in _ACRONYMS:
            return token.upper()
        return token.capitalize()

    return re.sub(r"[^\W_]+", word, value)
