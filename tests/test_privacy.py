from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pdk.privacy import (
    DEFAULT_MODEL_NAME,
    detect_private_data,
    load_model_config,
    redact_private_data,
)


class PrivacyTest(TestCase):
    def test_model_detector_maps_transformers_entities_to_private_findings(self):
        def fake_pipeline(text: str):
            start = text.index("Иван Петров")
            return [
                {
                    "entity_group": "PER",
                    "score": 0.96,
                    "start": start,
                    "end": start + len("Иван Петров"),
                }
            ]

        with patch("pdk.privacy._transformers_pipeline", return_value=fake_pipeline):
            findings = detect_private_data(
                "Контакт: Иван Петров",
                use_model=True,
                model_name="fake-russian-ner",
                model_threshold=0.8,
            )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].name, "ml_person")
        self.assertEqual(findings[0].label, "person name")
        self.assertEqual(findings[0].text, "Иван Петров")
        self.assertEqual(findings[0].detector, "transformers:fake-russian-ner")

    def test_model_detector_respects_threshold_and_redacts(self):
        def fake_pipeline(text: str):
            start = text.index("ООО Ромашка")
            return [
                {
                    "entity_group": "ORG",
                    "score": 0.55,
                    "start": start,
                    "end": start + len("ООО Ромашка"),
                },
                {
                    "entity_group": "ORG",
                    "score": 0.91,
                    "start": start,
                    "end": start + len("ООО Ромашка"),
                },
            ]

        with patch("pdk.privacy._transformers_pipeline", return_value=fake_pipeline):
            redacted = redact_private_data(
                "Клиент: ООО Ромашка",
                use_model=True,
                model_name="fake-russian-ner",
                model_threshold=0.8,
            )

        self.assertEqual(redacted, "Клиент: <ML_ORGANIZATION_1>")

    def test_model_config_can_be_loaded_from_global_and_profile_tables(self):
        config = Path(self.create_temp_file())
        config.write_text(
            "\n".join(
                [
                    "[model]",
                    "enabled = true",
                    'model = "base-model"',
                    "threshold = 0.7",
                    "",
                    "[profiles.client_a.model]",
                    'model = "client-model"',
                    "threshold = 0.9",
                ]
            ),
            encoding="utf-8",
        )

        default_config = load_model_config([config])
        profile_config = load_model_config([config], profile="client_a")

        self.assertTrue(default_config["enabled"])
        self.assertEqual(default_config["model"], "base-model")
        self.assertEqual(default_config["threshold"], 0.7)
        self.assertEqual(profile_config["model"], "client-model")
        self.assertEqual(profile_config["threshold"], 0.9)

    def test_default_model_config_is_disabled_until_requested(self):
        config = load_model_config([])

        self.assertFalse(config["enabled"])
        self.assertEqual(config["backend"], "transformers")
        self.assertEqual(config["model"], DEFAULT_MODEL_NAME)

    def create_temp_file(self) -> str:
        import tempfile

        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        return handle.name
