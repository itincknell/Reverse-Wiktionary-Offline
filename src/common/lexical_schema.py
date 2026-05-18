"""
Shared lexical schema constants.

Offline preprocessing and web serving use the same part-of-speech vocabulary so
the indexed data contract and filter UI cannot drift independently.
"""

ALLOWED_POS = (
    "noun",
    "verb",
    "adj",
    "adv",
    "name",
    "proper noun",
    "phrase",
    "proverb",
    "idiom",
)

