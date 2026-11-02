"""Tools for the Erasmus Inbox Agent.

Framework-agnostic helpers that the ADK agent (agent.py) wraps as tools:
reading emails from inbox/, filing attachments under filed/, updating
students.xlsx (one row per student) and saving reply drafts for staff.

All functions accept explicit directory/path arguments so they can be
tested without touching the real project folders.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

from dotenv import load_dotenv
from openpyxl import Workbook, load_workbook

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INBOX_DIR = Path(os.getenv("ERASMUS_INBOX_DIR", str(PROJECT_ROOT / "inbox")))
FILED_DIR = Path(os.getenv("ERASMUS_FILED_DIR", str(PROJECT_ROOT / "filed")))
XLSX_PATH = Path(os.getenv("ERASMUS_XLSX_PATH", str(PROJECT_ROOT / "students.xlsx")))
DRAFTS_DIR = Path(os.getenv("ERASMUS_DRAFTS_DIR", str(PROJECT_ROOT / "drafts")))

XLSX_HEADER = [
    "Surname",
    "Name",
    "Host University",
    "Stay Start",
    "Stay End",
    "Academic Year",
    "Last Document",
    "Last Updated",
]


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class ParsedEmail:
    subject: str
    from_name: str
    from_email: str
    body: str
    attachments: list[Attachment]


def list_inbox_emails(inbox_dir: Path | str = INBOX_DIR) -> list[str]:
    """Return all .eml files in the inbox folder as path strings, sorted by name.

    Returns plain strings (not Path objects) so the result is JSON-serializable
    when ADK sends it back to the model as a function_response.
    """
    inbox_dir = Path(inbox_dir)
    if not inbox_dir.is_dir():
        return []
    return [str(p) for p in sorted(inbox_dir.glob("*.eml"))]


def _parsed_to_json(email: ParsedEmail) -> dict:
    """Convert ParsedEmail to a JSON-safe dict: attachment bytes become base64 strings."""
    return {
        "subject": email.subject,
        "from_name": email.from_name,
        "from_email": email.from_email,
        "body": email.body,
        "attachments": [
            {
                "filename": att.filename,
                "content_type": att.content_type,
                "data": base64.b64encode(att.data).decode("ascii"),
            }
            for att in email.attachments
        ],
    }


def parse_email(path: Path | str) -> dict:
    """Parse one .eml file and return a JSON-safe dict.

    Keys: subject, from_name, from_email, body, attachments.
    Each attachment is {"filename", "content_type", "data"} with data as a
    base64 string (raw bytes are not JSON-serializable).
    """
    msg = BytesParser(policy=policy.default).parsebytes(Path(path).read_bytes())
    body_parts: list[str] = []
    attachments: list[Attachment] = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                Attachment(
                    filename=part.get_filename() or "attachment.bin",
                    content_type=part.get_content_type(),
                    data=payload,
                )
            )
        elif part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
            payload = part.get_payload(decode=True)
            if payload:
                body_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    from_header = str(msg.get("From", ""))
    from_name, _, from_email = from_header.partition("<")
    return _parsed_to_json(
        ParsedEmail(
            subject=str(msg.get("Subject", "")),
            from_name=from_name.strip().strip('"'),
            from_email=from_email.rstrip(">").strip(),
            body="\n".join(body_parts).strip(),
            attachments=attachments,
        )
    )


def slugify(text: str) -> str:
    """Make a filesystem-safe token: keep letters/digits/underscore/hyphen, drop the rest."""
    return re.sub(r"[^\w-]", "", text.strip(), flags=re.UNICODE)


def student_folder_name(surname: str, name: str) -> str:
    """Folder name for a student: Surname_Name (e.g. Shevchenko_Taras)."""
    return f"{slugify(surname)}_{slugify(name)}"


def academic_year_label(d: date | datetime | str) -> str:
    """Academic year label like '2026-27'. Autumn (month>=8) starts the year, spring belongs to the previous one."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    elif isinstance(d, datetime):
        d = d.date()
    if d.month >= 8:
        return f"{d.year}-{str(d.year + 1)[-2:]}"
    return f"{d.year - 1}-{str(d.year)[-2:]}"


def build_filed_path(
    surname: str,
    name: str,
    doc_type: str,
    year_label: str,
    original_filename: str = "document.pdf",
    filed_dir: Path | str = FILED_DIR,
) -> Path:
    """Build the target path: filed/Surname_Name/Surname_Name_DocType_2026-27.pdf.

    The real extension of the attachment is kept (a photo stays .jpg),
    defaulting to .pdf when the original name has no extension.
    """
    folder = student_folder_name(surname, name)
    ext = Path(original_filename).suffix.lower() or ".pdf"
    filename = f"{folder}_{slugify(doc_type)}_{year_label}{ext}"
    return Path(filed_dir) / folder / filename


def save_attachment(
    data: bytes | str,
    surname: str,
    name: str,
    doc_type: str,
    year_label: str,
    original_filename: str = "document.pdf",
    filed_dir: Path | str = FILED_DIR,
) -> str:
    """Save one attachment under filed/ and return the path as a string.

    If the target file already exists, a numeric suffix is added instead of overwriting.
    Accepts bytes or a str (base64 is tried first, then plain utf-8) because LLM tool
    arguments arrive as JSON strings.
    """
    if isinstance(data, str):
        try:
            import base64

            data = base64.b64decode(data, validate=True)
        except Exception:
            data = data.encode("utf-8")
    target = build_filed_path(surname, name, doc_type, year_label, original_filename, filed_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stem, ext = target.stem, target.suffix
        counter = 2
        while True:
            candidate = target.with_name(f"{stem}_{counter}{ext}")
            if not candidate.exists():
                target = candidate
                break
            counter += 1
    target.write_bytes(data)
    return str(target)


def _to_iso_date(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


def upsert_student_row(
    surname: str,
    name: str,
    xlsx_path: Path | str = XLSX_PATH,
    host_university: str | None = None,
    stay_start: date | datetime | str | None = None,
    stay_end: date | datetime | str | None = None,
    academic_year: str | None = None,
    last_document: str | None = None,
) -> dict:
    """Insert or update the student's row in students.xlsx and return it as a dict.

    The row is matched by Surname + Name (case-insensitive). Only fields that
    are not None are overwritten; 'Last Updated' is always set to today.
    """
    xlsx_path = Path(xlsx_path)
    if xlsx_path.exists():
        wb = load_workbook(xlsx_path)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Students"
        ws.append(XLSX_HEADER)

    updates = {
        "Host University": host_university,
        "Stay Start": _to_iso_date(stay_start),
        "Stay End": _to_iso_date(stay_end),
        "Academic Year": academic_year,
        "Last Document": last_document,
        "Last Updated": date.today().isoformat(),
    }
    col_index = {cell.value: cell.column for cell in ws[1]}

    target_row = None
    for row in ws.iter_rows(min_row=2):
        if str(row[0].value or "").casefold() == surname.casefold() and str(row[1].value or "").casefold() == name.casefold():
            target_row = row[0].row
            break

    if target_row is None:
        target_row = ws.max_row + 1
        ws.cell(row=target_row, column=col_index["Surname"], value=surname)
        ws.cell(row=target_row, column=col_index["Name"], value=name)

    for header, value in updates.items():
        if value is not None:
            ws.cell(row=target_row, column=col_index[header], value=value)

    for i, _ in enumerate(XLSX_HEADER, start=1):
        ws.column_dimensions[chr(64 + i)].width = 22

    wb.save(xlsx_path)

    def _json_safe(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, (bytes, bytearray)):
            return base64.b64encode(bytes(value)).decode("ascii")
        return value

    return {header: _json_safe(ws.cell(row=target_row, column=col_index[header]).value) for header in XLSX_HEADER}


def save_reply_draft(
    to_name: str,
    subject: str,
    body: str,
    drafts_dir: Path | str = DRAFTS_DIR,
) -> str:
    """Save a reply draft for staff to review and send. Returns the file path."""
    drafts_dir = Path(drafts_dir)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{stamp}_{slugify(to_name) or 'student'}.txt"
    path = drafts_dir / filename
    path.write_text(f"To: {to_name}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    return str(path)
