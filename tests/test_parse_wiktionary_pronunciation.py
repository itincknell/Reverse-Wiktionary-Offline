import unittest

from src.embeddings.parse_wiktionary import (
    extract_pronunciation_fields,
    normalize_record,
)


class PronunciationExtractionTests(unittest.TestCase):
    def test_extracts_first_non_empty_values_in_sound_order(self) -> None:
        fields = extract_pronunciation_fields(
            [
                {"ipa": "  /first/  "},
                {
                    "ipa": "/second/",
                    "ogg_url": " https://example.test/audio.ogg ",
                },
                {"mp3_url": " https://example.test/audio.mp3 "},
            ]
        )

        self.assertEqual(
            fields,
            {
                "ipa": "/first/",
                "audio_ogg_url": "https://example.test/audio.ogg",
                "audio_mp3_url": "https://example.test/audio.mp3",
            },
        )

    def test_missing_or_malformed_sounds_emit_no_fields(self) -> None:
        self.assertEqual(extract_pronunciation_fields(None), {})
        self.assertEqual(extract_pronunciation_fields({"ipa": "/nope/"}), {})
        self.assertEqual(extract_pronunciation_fields(["bad", {}]), {})

    def test_english_prefers_general_american_values(self) -> None:
        fields = extract_pronunciation_fields(
            [
                {
                    "tags": ["Received-Pronunciation"],
                    "ipa": "/rp/",
                    "ogg_url": "https://example.test/rp.ogg",
                    "mp3_url": "https://example.test/rp.mp3",
                },
                {
                    "tags": ["General-American"],
                    "ipa": "/ga/",
                    "ogg_url": "https://example.test/ga.ogg",
                    "mp3_url": "https://example.test/ga.mp3",
                },
            ],
            lang="English",
        )

        self.assertEqual(
            fields,
            {
                "ipa": "/ga/",
                "audio_ogg_url": "https://example.test/ga.ogg",
                "audio_mp3_url": "https://example.test/ga.mp3",
            },
        )

    def test_non_english_does_not_prefer_general_american_values(self) -> None:
        fields = extract_pronunciation_fields(
            [
                {
                    "tags": ["Received-Pronunciation"],
                    "ipa": "/first/",
                    "ogg_url": "https://example.test/first.ogg",
                    "mp3_url": "https://example.test/first.mp3",
                },
                {
                    "tags": ["General-American"],
                    "ipa": "/second/",
                    "ogg_url": "https://example.test/second.ogg",
                    "mp3_url": "https://example.test/second.mp3",
                },
            ],
            lang="German",
        )

        self.assertEqual(
            fields,
            {
                "ipa": "/first/",
                "audio_ogg_url": "https://example.test/first.ogg",
                "audio_mp3_url": "https://example.test/first.mp3",
            },
        )

    def test_normalize_record_preserves_embedding_text(self) -> None:
        rows = normalize_record(
            {
                "lang": "English",
                "word": "free",
                "pos": "adj",
                "senses": [{"glosses": [" Not imprisoned or enslaved. "]}],
                "sounds": [
                    {"ipa": "/fɹiː/"},
                    {
                        "ogg_url": "https://example.test/free.ogg",
                        "mp3_url": "https://example.test/free.mp3",
                    },
                ],
            }
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["embedding_text"], "Not imprisoned or enslaved.")
        self.assertEqual(row["ipa"], "/fɹiː/")
        self.assertEqual(row["audio_ogg_url"], "https://example.test/free.ogg")
        self.assertEqual(row["audio_mp3_url"], "https://example.test/free.mp3")

    def test_normalize_record_prefers_general_american_for_english(self) -> None:
        rows = normalize_record(
            {
                "lang": "English",
                "word": "free",
                "pos": "adj",
                "senses": [{"glosses": ["Not imprisoned or enslaved."]}],
                "sounds": [
                    {
                        "tags": ["Received-Pronunciation"],
                        "ipa": "/fɹiː/",
                        "ogg_url": "https://example.test/free-rp.ogg",
                    },
                    {
                        "tags": ["General-American"],
                        "ipa": "/fɹi/",
                        "ogg_url": "https://example.test/free-ga.ogg",
                        "mp3_url": "https://example.test/free-ga.mp3",
                    },
                ],
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ipa"], "/fɹi/")
        self.assertEqual(rows[0]["audio_ogg_url"], "https://example.test/free-ga.ogg")
        self.assertEqual(rows[0]["audio_mp3_url"], "https://example.test/free-ga.mp3")

    def test_normalize_record_omits_missing_pronunciation_fields(self) -> None:
        rows = normalize_record(
            {
                "lang": "English",
                "word": "book",
                "pos": "noun",
                "senses": [{"glosses": ["A written work."]}],
                "sounds": [{"audio": "Book.ogg"}],
            }
        )

        self.assertEqual(len(rows), 1)
        self.assertNotIn("ipa", rows[0])
        self.assertNotIn("audio_ogg_url", rows[0])
        self.assertNotIn("audio_mp3_url", rows[0])


if __name__ == "__main__":
    unittest.main()
