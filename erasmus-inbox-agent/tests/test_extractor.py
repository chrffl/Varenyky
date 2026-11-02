"""Offline tests for erasmus_inbox/extractor.py — no real Gemini calls, no network.

The genai.Client is mocked; run with either:
    .venv/Scripts/python.exe -m pytest tests/test_extractor.py -v
    .venv/Scripts/python.exe -m unittest tests.test_extractor -v
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from erasmus_inbox import extractor
from erasmus_inbox.tools import ParsedEmail


def make_client(payload=None, text=None):
    """Mock genai client whose generate_content returns a response with .text JSON."""
    client = MagicMock()
    response = MagicMock()
    response.parsed = None
    response.text = text if text is not None else json.dumps(payload)
    client.models.generate_content.return_value = response
    return client


FULL_PAYLOAD = {
    "surname": "Shevchenko",
    "name": "Taras",
    "doc_type": "learning_agreement",
    "academic_year": "2026-27",
    "host_university": "University of Warsaw",
    "stay_start": "2026-10-01",
    "stay_end": "2027-02-15",
    "confidence": "high",
}

EMAIL_DICT = {
    "from_name": "Taras Shevchenko",
    "from_email": "taras.shevchenko@example.com",
    "subject": "My Learning Agreement",
    "body": "Hi, attached is my signed LA. Warsaw, 2026-10-01 to 2027-02-15.",
    "attachments": [],
}


class ExtractDocumentDataTests(unittest.TestCase):
    def call_extractor(self, client, email=EMAIL_DICT, attachment_text=None):
        with (
            patch.object(extractor.genai, "Client", return_value=client),
            patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}),
        ):
            return extractor.extract_document_data(email, attachment_text=attachment_text)

    def test_success_returns_exact_keys_and_values(self):
        client = make_client(FULL_PAYLOAD)
        result = self.call_extractor(client)
        self.assertEqual(set(result.keys()), set(extractor.RESULT_KEYS))
        self.assertEqual(result, FULL_PAYLOAD)
        client.models.generate_content.assert_called_once()

    def test_uses_json_mode_schema_and_model(self):
        client = make_client(FULL_PAYLOAD)
        self.call_extractor(client)
        kwargs = client.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], extractor.MODEL)
        config = kwargs["config"]
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.response_schema["properties"]["doc_type"]["enum"], extractor.DOC_TYPES)
        self.assertIn("Erasmus", config.system_instruction)

    def test_extra_model_keys_are_dropped(self):
        payload = {**FULL_PAYLOAD, "hallucinated_field": "x"}
        result = self.call_extractor(make_client(payload))
        self.assertNotIn("hallucinated_field", result)
        self.assertEqual(set(result.keys()), set(extractor.RESULT_KEYS))

    def test_normalizes_capitalize_and_year(self):
        payload = {
            "surname": "shevchenko",
            "name": "taras",
            "doc_type": "insurance",
            "academic_year": "2026/2027",
            "host_university": "  Gdansk University of Technology  ",
            "stay_start": None,
            "stay_end": None,
            "confidence": "medium",
        }
        result = self.call_extractor(make_client(payload))
        self.assertEqual(result["surname"], "Shevchenko")
        self.assertEqual(result["name"], "Taras")
        self.assertEqual(result["academic_year"], "2026-27")
        self.assertEqual(result["host_university"], "Gdansk University of Technology")
        self.assertIsNone(result["stay_start"])

    def test_missing_fields_become_none(self):
        payload = {"doc_type": "unknown", "confidence": "low"}
        result = self.call_extractor(make_client(payload))
        self.assertEqual(set(result.keys()), set(extractor.RESULT_KEYS))
        self.assertEqual(result["doc_type"], "unknown")
        self.assertEqual(result["confidence"], "low")
        for key in ("surname", "name", "academic_year", "host_university", "stay_start", "stay_end"):
            self.assertIsNone(result[key])

    def test_unknown_doc_type_is_signal_not_exception(self):
        result = self.call_extractor(make_client({"doc_type": "unknown", "confidence": "low"}))
        self.assertEqual(result["doc_type"], "unknown")

    def test_invalid_doc_type_falls_back_to_unknown(self):
        payload = {**FULL_PAYLOAD, "doc_type": "random_thing"}
        result = self.call_extractor(make_client(payload))
        self.assertEqual(result["doc_type"], "unknown")

    def test_year_derived_from_stay_start_when_missing(self):
        payload = {**FULL_PAYLOAD, "academic_year": None}
        result = self.call_extractor(make_client(payload))
        self.assertEqual(result["academic_year"], "2026-27")

    def test_api_error_returns_error_dict_never_raises(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("network down")
        result = self.call_extractor(client)
        self.assertEqual(result["doc_type"], "unknown")
        self.assertEqual(result["confidence"], "low")
        self.assertIn("network down", result["error"])
        self.assertEqual(set(result.keys()), set(extractor.RESULT_KEYS) | {"error"})

    def test_missing_api_key_returns_error_dict(self):
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_API_KEY"}
        client = make_client(FULL_PAYLOAD)
        with (
            patch.object(extractor.genai, "Client", return_value=client),
            patch.dict(os.environ, env, clear=True),
        ):
            result = extractor.extract_document_data(EMAIL_DICT)
        self.assertEqual(result["doc_type"], "unknown")
        self.assertEqual(result["confidence"], "low")
        self.assertIn("GOOGLE_API_KEY", result["error"])
        client.models.generate_content.assert_not_called()

    def test_broken_json_returns_error_dict(self):
        result = self.call_extractor(make_client(text="not json at all"))
        self.assertEqual(result["doc_type"], "unknown")
        self.assertIn("error", result)

    def test_parsed_email_object_accepted(self):
        email = ParsedEmail(
            subject="insurance",
            from_name="Olena Koval",
            from_email="olena@example.com",
            body="here is my insurance",
            attachments=[],
        )
        result = self.call_extractor(make_client({"doc_type": "insurance", "confidence": "high"}), email=email)
        self.assertEqual(result["doc_type"], "insurance")

    def test_pdf_attachment_text_sent_to_model(self):
        email = {**EMAIL_DICT, "attachments": [{"filename": "scan_0042.pdf", "data": b"%PDF-1.4 fake"}]}
        client = make_client(FULL_PAYLOAD)
        with (
            patch.object(extractor.genai, "Client", return_value=client),
            patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}),
            patch.object(extractor, "_pdf_attachment_text", return_value="PDF TEXT CONTENT"),
        ):
            extractor.extract_document_data(email)
        contents = client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("PDF TEXT CONTENT", contents)
        self.assertIn("taras.shevchenko@example.com", contents)

    def test_explicit_attachment_text_wins_over_pdf(self):
        email = {**EMAIL_DICT, "attachments": [{"filename": "scan.pdf", "data": b"%PDF-1.4 fake"}]}
        client = make_client(FULL_PAYLOAD)
        with (
            patch.object(extractor.genai, "Client", return_value=client),
            patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}),
            patch.object(extractor, "_pdf_attachment_text", return_value="PDF TEXT") as pdf_mock,
        ):
            extractor.extract_document_data(email, attachment_text="EXPLICIT TEXT")
        contents = client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("EXPLICIT TEXT", contents)
        pdf_mock.assert_not_called()


    def test_result_is_json_serializable(self):
        result = self.call_extractor(make_client(FULL_PAYLOAD))
        json.dumps(result)  # ADK must be able to serialize the tool result

    def test_non_string_model_values_are_coerced_to_json_safe(self):
        payload = {**FULL_PAYLOAD, "stay_start": ["2026-10-01"], "host_university": 123}
        result = self.call_extractor(make_client(payload))
        json.dumps(result)
        self.assertIsInstance(result["stay_start"], str)
        self.assertIsInstance(result["host_university"], str)

    def test_accepts_parse_email_dict_output(self):
        """Roundtrip: tools.parse_email() dict (base64 attachments) -> extract_document_data."""
        import tempfile
        from email.message import EmailMessage
        from pathlib import Path

        from erasmus_inbox import tools as tools_mod

        tmp = Path(tempfile.mkdtemp())
        msg = EmailMessage()
        msg["From"] = '"Olena Koval" <olena@example.com>'
        msg["Subject"] = "insurance"
        msg.set_content("my insurance photo")
        msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="scan.pdf")
        eml = tmp / "e.eml"
        eml.write_bytes(msg.as_bytes())

        parsed = tools_mod.parse_email(eml)
        json.dumps(parsed)

        client = make_client({"doc_type": "insurance", "confidence": "high"})
        with (
            patch.object(extractor.genai, "Client", return_value=client),
            patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}),
            patch.object(extractor, "_pdf_attachment_text", return_value="PDF TEXT") as pdf_mock,
        ):
            result = extractor.extract_document_data(parsed)
        self.assertEqual(result["doc_type"], "insurance")
        pdf_mock.assert_called_once_with(b"%PDF-1.4 fake")  # base64 decoded back to bytes


class ResolveAcademicYearTests(unittest.TestCase):
    def test_cases(self):
        cases = {
            "2026-27": "2026-27",
            "2026/2027": "2026-27",
            "2026/27": "2026-27",
            "2026–2027": "2026-27",
            "2026-2027": "2026-27",
            "осінь 2026": "2026-27",
            "autumn 2026": "2026-27",
            "fall 2026": "2026-27",
            "весна 2027": "2026-27",
            "spring 2027": "2026-27",
            "2026-10-01": "2026-27",
            "2027-02-15": "2026-27",
            "2026": "2026-27",
            "2025-27": None,
            "hello": None,
            "": None,
            None: None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(extractor.resolve_academic_year(raw), expected)


if __name__ == "__main__":
    unittest.main()
