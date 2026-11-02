"""Offline tests for erasmus_inbox/tools.py.

Critical regression guard: every value returned by a tool must survive
json.dumps() — ADK serializes tool results to JSON before sending them
to the model as function_response, and pathlib.Path / bytes / datetime
are not JSON serializable (this exact bug once crashed Mode A).

Run with: .venv/Scripts/python.exe -m pytest tests/ -v
"""

import base64
import json
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from erasmus_inbox import tools

PDF_BYTES = b"%PDF-1.4 fake learning agreement bytes"
JPG_BYTES = b"\xff\xd8\xff fake photo bytes"


def make_eml(path: Path, frm: str, name: str, subject: str, body: str,
             att_name: str, att_bytes: bytes, att_subtype: str) -> None:
    msg = EmailMessage()
    msg["From"] = f'"{name}" <{frm}>'
    msg["To"] = "erasmus@university.example"
    msg["Subject"] = subject
    msg.set_content(body)
    maintype = "application" if att_subtype == "pdf" else "image"
    msg.add_attachment(att_bytes, maintype=maintype, subtype=att_subtype, filename=att_name)
    path.write_bytes(msg.as_bytes())


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inbox = self.tmp / "inbox"
        self.filed = self.tmp / "filed"
        self.drafts = self.tmp / "drafts"
        self.xlsx = self.tmp / "students.xlsx"
        self.inbox.mkdir()
        make_eml(self.inbox / "001.eml", "taras.shevchenko@example.com", "Taras Shevchenko",
                 "My Learning Agreement", "Hi, attached is my signed LA. Warsaw 2026-10-01 to 2027-02-15.",
                 "scan_0042.pdf", PDF_BYTES, "pdf")
        make_eml(self.inbox / "002.eml", "olena.koval@example.com", "Olena Koval",
                 "insurance", "here is my insurance photo, Gdansk spring 2027",
                 "IMG_2231.jpg", JPG_BYTES, "jpeg")

    def test_list_inbox_emails_returns_json_safe_str_list(self):
        result = tools.list_inbox_emails(self.inbox)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(p, str) for p in result), result)
        json.dumps(result)

    def test_list_inbox_emails_missing_dir_returns_empty_list(self):
        result = tools.list_inbox_emails(self.tmp / "nope")
        self.assertEqual(result, [])
        json.dumps(result)

    def test_parse_email_returns_json_safe_dict(self):
        result = tools.parse_email(str(self.inbox / "001.eml"))
        json.dumps(result)  # must not raise
        self.assertEqual(set(result.keys()), {"subject", "from_name", "from_email", "body", "attachments"})
        self.assertEqual(result["from_name"], "Taras Shevchenko")
        self.assertEqual(result["from_email"], "taras.shevchenko@example.com")
        self.assertIn("signed LA", result["body"])
        att = result["attachments"][0]
        self.assertEqual(set(att.keys()), {"filename", "content_type", "data"})
        self.assertEqual(att["filename"], "scan_0042.pdf")
        self.assertIsInstance(att["data"], str)
        self.assertEqual(base64.b64decode(att["data"]), PDF_BYTES)

    def test_save_attachment_returns_json_safe_str(self):
        path = tools.save_attachment(PDF_BYTES, "Shevchenko", "Taras", "learning_agreement",
                                     "2026-27", "scan_0042.pdf", filed_dir=self.filed)
        self.assertIsInstance(path, str)
        json.dumps(path)
        self.assertEqual(Path(path).read_bytes(), PDF_BYTES)
        self.assertTrue(path.endswith("Shevchenko_Taras_learning_agreement_2026-27.pdf"))

    def test_save_attachment_accepts_base64_str(self):
        path = tools.save_attachment(base64.b64encode(JPG_BYTES).decode("ascii"), "Koval", "Olena",
                                     "insurance", "2026-27", "IMG_2231.jpg", filed_dir=self.filed)
        self.assertEqual(Path(path).read_bytes(), JPG_BYTES)
        self.assertTrue(path.endswith(".jpg"))
        json.dumps(path)

    def test_save_attachment_does_not_overwrite(self):
        p1 = tools.save_attachment(PDF_BYTES, "Shevchenko", "Taras", "learning_agreement",
                                   "2026-27", "a.pdf", filed_dir=self.filed)
        p2 = tools.save_attachment(PDF_BYTES, "Shevchenko", "Taras", "learning_agreement",
                                   "2026-27", "a.pdf", filed_dir=self.filed)
        self.assertNotEqual(p1, p2)
        self.assertTrue(Path(p1).exists() and Path(p2).exists())

    def test_upsert_student_row_returns_json_safe_dict(self):
        row = tools.upsert_student_row("Shevchenko", "Taras", self.xlsx,
                                       host_university="University of Warsaw",
                                       stay_start="2026-10-01", stay_end="2027-02-15",
                                       academic_year="2026-27", last_document="learning_agreement")
        json.dumps(row)  # must not raise
        self.assertEqual(row["Surname"], "Shevchenko")
        self.assertEqual(row["Stay Start"], "2026-10-01")
        self.assertIsNotNone(row["Last Updated"])

        # second call updates the same row, does not duplicate it
        row2 = tools.upsert_student_row("Shevchenko", "Taras", self.xlsx, last_document="insurance")
        json.dumps(row2)
        self.assertEqual(row2["Host University"], "University of Warsaw")
        self.assertEqual(row2["Last Document"], "insurance")

        from openpyxl import load_workbook
        ws = load_workbook(self.xlsx).active
        self.assertEqual(ws.max_row, 2)  # header + 1 student

    def test_upsert_student_row_accepts_date_objects(self):
        from datetime import date
        row = tools.upsert_student_row("Koval", "Olena", self.xlsx,
                                       stay_start=date(2027, 2, 1), stay_end=date(2027, 6, 30))
        json.dumps(row)
        self.assertEqual(row["Stay Start"], "2027-02-01")

    def test_save_reply_draft_returns_json_safe_str(self):
        path = tools.save_reply_draft("Taras Shevchenko", "Re: LA", "Dear Taras, ...", drafts_dir=self.drafts)
        self.assertIsInstance(path, str)
        json.dumps(path)
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("Dear Taras, ...", content)

    def test_all_tool_results_pass_json_dumps(self):
        """The regression test for the WindowsPath bug: json.dumps on every tool result."""
        results = [
            tools.list_inbox_emails(self.inbox),
            tools.parse_email(str(self.inbox / "001.eml")),
            tools.save_attachment(PDF_BYTES, "Shevchenko", "Taras", "learning_agreement",
                                  "2026-27", "scan_0042.pdf", filed_dir=self.filed),
            tools.upsert_student_row("Shevchenko", "Taras", self.xlsx, academic_year="2026-27"),
            tools.save_reply_draft("Taras Shevchenko", "Re: LA", "body", drafts_dir=self.drafts),
        ]
        for result in results:
            json.dumps(result)  # raises TypeError on Path/bytes/datetime

    def test_helpers(self):
        self.assertEqual(tools.slugify("Shevchenko"), "Shevchenko")
        self.assertEqual(tools.student_folder_name("Коваль", "Олена"), "Коваль_Олена")
        self.assertEqual(tools.academic_year_label("2026-10-01"), "2026-27")
        self.assertEqual(tools.academic_year_label("2027-02-15"), "2026-27")


if __name__ == "__main__":
    unittest.main()
