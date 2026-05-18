"""
Shared lexical schema constants.

Offline preprocessing and downstream query consumers use the same
part-of-speech vocabulary so indexed data and filters cannot drift
independently.
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
