"""Gemini-based extraction of structured data from student emails.

extract_document_data() sends the email (sender, subject, body) plus the
attachment text (if any) to Gemini with a JSON response schema and returns
a dict with exactly these keys:
    surname, name, doc_type, academic_year, host_university,
    stay_start, stay_end, confidence
On any failure it returns the same shape with doc_type="unknown",
confidence="low" and an extra "error" key — it never raises.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv
from google import genai

from .tools import academic_year_label

load_dotenv()

MODEL = os.getenv("ERASMUS_MODEL", "gemini-3.8-flash")

DOC_TYPES = [
    "learning_agreement",
    "transcript",
    "insurance",
    "certificate_of_arrival",
    "unknown",
]

RESULT_KEYS = [
    "surname",
    "name",
    "doc_type",
    "academic_year",
    "host_university",
    "stay_start",
    "stay_end",
    "confidence",
]

DOC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "surname": {"type": "string", "nullable": True},
        "name": {"type": "string", "nullable": True},
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "academic_year": {"type": "string", "nullable": True},
        "host_university": {"type": "string", "nullable": True},
        "stay_start": {"type": "string", "nullable": True},
        "stay_end": {"type": "string", "nullable": True},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["doc_type", "confidence"],
}

SYSTEM_PROMPT = """Ти читаєш листи студентів Erasmus. Витягуй ТОЛЬКО ті дані, що реально присутні в тексті. Краще null, ніж вигадка. Студенти пишуть з помилками (наприклад "Shevcenko Taras"), передавай як написано, але з нормальним capitalize. Дати бери у форматі YYYY-MM-DD.

Поверни JSON з полями:
- surname, name: прізвище та ім'я студента латиницею (або як у підписі), з великої літери. null, якщо не вказано.
- doc_type: один з "learning_agreement", "transcript", "insurance", "certificate_of_arrival". Якщо неясно — "unknown".
- academic_year: навчальний рік у форматі "2026-27". Якщо в тексті є лише дата (наприклад дата початку обміну), обчисли навчальний рік від неї: осінь (серпень-грудень) починає навчальний рік, весна (січень-липень) належить до попереднього. null, якщо визначити неможливо.
- host_university: назва хост-університету, якщо згадана. null інакше.
- stay_start, stay_end: дати початку і кінця обміну у форматі YYYY-MM-DD, якщо вказані. null інакше.
- confidence: "high", якщо всі ключові поля (прізвище, ім'я, doc_type) однозначні; "medium", якщо частина полів припущена; "low", якщо майже нічого не зрозуміло або doc_type="unknown".

Відповідай ЛИШЕ JSON, без пояснень."""


def _error_result(message: str) -> dict:
    result = {key: None for key in RESULT_KEYS}
    result["doc_type"] = "unknown"
    result["confidence"] = "low"
    result["error"] = message
    return result


def _capitalize(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value.capitalize() if value.islower() else value


def _json_safe(value: Any) -> Any:
    """Coerce a model-returned value to something json.dumps() accepts."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    return str(value)


def _pdf_attachment_text(data: bytes) -> str | None:
    """Extract text from a PDF attachment via pypdf. Returns None if unreadable or pypdf missing."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        return text or None
    except Exception:
        return None


def _attachment_bytes(att: Any) -> tuple[str, bytes] | None:
    """Normalize one attachment (Attachment dataclass or dict) to (filename, data)."""
    if isinstance(att, dict):
        filename = att.get("filename", "")
        data = att.get("data", b"")
    else:
        filename = getattr(att, "filename", "")
        data = getattr(att, "data", b"")
    if isinstance(data, str):
        # parse_email() returns attachment data as a base64 string
        try:
            data = base64.b64decode(data, validate=True)
        except Exception:
            data = data.encode("utf-8", errors="replace")
    if not isinstance(data, (bytes, bytearray)) or not data:
        return None
    return filename, bytes(data)


def _email_to_text(email: Any, want_attachment: bool = True) -> tuple[str, str, str, str, str | None]:
    """Normalize parse_email() output (ParsedEmail or dict) to (from_name, from_email, subject, body, attachment_text)."""
    if isinstance(email, dict):
        from_name = str(email.get("from_name") or email.get("sender") or "")
        from_email = str(email.get("from_email") or email.get("sender") or "")
        subject = str(email.get("subject") or "")
        body = str(email.get("body") or "")
        attachments = email.get("attachments") or []
    else:
        from_name = str(getattr(email, "from_name", "") or "")
        from_email = str(getattr(email, "from_email", "") or "")
        subject = str(getattr(email, "subject", "") or "")
        body = str(getattr(email, "body", "") or "")
        attachments = getattr(email, "attachments", []) or []

    attachment_text = None
    if want_attachment:
        for att in attachments:
            parsed = _attachment_bytes(att)
            if parsed is None:
                continue
            filename, data = parsed
            if filename.lower().endswith(".pdf"):
                attachment_text = _pdf_attachment_text(data)
                if attachment_text:
                    break
    return from_name, from_email, subject, body, attachment_text


def extract_document_data(email: dict, attachment_text: str | None = None) -> dict:
    """Call Gemini once and return structured data about the email + attachment.

    Always returns a dict with exactly RESULT_KEYS (plus "error" on failure).
    Never raises: API/key/parse problems become doc_type="unknown",
    confidence="low", error=<message>.
    """
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set (check .env)")

        from_name, from_email, subject, body, pdf_text = _email_to_text(
            email, want_attachment=attachment_text is None
        )
        if attachment_text is None:
            attachment_text = pdf_text

        user_msg = (
            f"From: {from_name} <{from_email}>\n"
            f"Subject: {subject}\n"
            f"Body:\n{body}\n\n"
            f"Attachment text:\n{attachment_text or '(no readable attachment text)'}"
        )

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=user_msg,
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=DOC_SCHEMA,
                temperature=0,
            ),
        )
        raw = getattr(response, "parsed", None)
        if raw is None:
            raw = json.loads(response.text)
        if not isinstance(raw, dict):
            raise ValueError(f"Gemini returned non-object JSON: {raw!r}")
    except Exception as exc:  # noqa: BLE001 - contract: never raise
        return _error_result(str(exc))

    result = {key: _json_safe(raw.get(key)) for key in RESULT_KEYS}
    result["surname"] = _capitalize(result["surname"])
    result["name"] = _capitalize(result["name"])
    if result["host_university"] is not None:
        result["host_university"] = str(result["host_university"]).strip() or None
    if result["doc_type"] not in DOC_TYPES:
        result["doc_type"] = "unknown"
    if result["confidence"] not in ("high", "medium", "low"):
        result["confidence"] = "low"
    result["academic_year"] = resolve_academic_year(result["academic_year"])
    if result["academic_year"] is None and result["stay_start"]:
        try:
            result["academic_year"] = academic_year_label(str(result["stay_start"]))
        except ValueError:
            pass
    return result


_YEAR_RANGE_RE = re.compile(r"(\d{4})\s*[-/–—.]\s*(\d{4}|\d{2})(?!\d)")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEASON_RE = re.compile(
    r"(осін\w*|autumn|fall|весн\w*|spring|зим\w*|winter|літ\w*|summer)\s*(\d{4})",
    re.IGNORECASE,
)
_BARE_YEAR_RE = re.compile(r"^\s*(\d{4})\s*$")

_SEASON_START_PREFIXES = ("осін", "autumn", "fall", "зим", "winter", "літ", "summer")
_SEASON_PREV_PREFIXES = ("весн", "spring")


def resolve_academic_year(raw: Any) -> str | None:
    """Normalize whatever Gemini returned ("2026-27", "2026/2027", "осінь 2026", a date) to "2026-27".

    Returns None if it cannot be interpreted.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    if _ISO_DATE_RE.match(text):
        try:
            return academic_year_label(date.fromisoformat(text))
        except ValueError:
            return None

    match = _YEAR_RANGE_RE.search(text)
    if match:
        start_year = int(match.group(1))
        end = match.group(2)
        end_year = int(end) if len(end) == 4 else 2000 + int(end)
        if end_year == start_year + 1:
            return f"{start_year}-{end_year % 100:02d}"
        return None

    season = _SEASON_RE.search(text.lower())
    if season:
        word, year = season.group(1).lower(), int(season.group(2))
        if word.startswith(_SEASON_START_PREFIXES):
            return f"{year}-{(year + 1) % 100:02d}"
        if word.startswith(_SEASON_PREV_PREFIXES):
            return f"{year - 1}-{year % 100:02d}"

    bare = _BARE_YEAR_RE.match(text)
    if bare:
        year = int(bare.group(1))
        return f"{year}-{(year + 1) % 100:02d}"

    return None
