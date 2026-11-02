import csv
import io
from abc import ABC, abstractmethod
from dataclasses import asdict, fields
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from sample_data import SAMPLES, Expected, SampleEmail

ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / "inbox"
EXPECTED_CSV = ROOT / "tests" / "expected.csv"

OFFICE_ADDRESS = "erasmus@university.example"
SENT_AT = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
LINE_HEIGHT = 24


class AttachmentRenderer(ABC):
    maintype: str
    subtype: str

    @abstractmethod
    def render(self, lines: tuple[str, ...]) -> bytes:
        ...


class PdfRenderer(AttachmentRenderer):
    maintype, subtype = "application", "pdf"

    def render(self, lines: tuple[str, ...]) -> bytes:
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        y = A4[1] - 80
        for line in lines:
            pdf.drawString(60, y, line)
            y -= LINE_HEIGHT
        pdf.save()
        return buffer.getvalue()


class JpegRenderer(AttachmentRenderer):
    maintype, subtype = "image", "jpeg"

    def render(self, lines: tuple[str, ...]) -> bytes:
        image = Image.new("RGB", (600, 60 + LINE_HEIGHT * len(lines)), "white")
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(lines):
            draw.text((30, 30 + index * LINE_HEIGHT), line, fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        return buffer.getvalue()


RENDERERS: dict[str, AttachmentRenderer] = {
    ".pdf": PdfRenderer(),
    ".jpg": JpegRenderer(),
}


class EmailBuilder:
    def __init__(self, renderers: dict[str, AttachmentRenderer]):
        self._renderers = renderers

    def build(self, sample: SampleEmail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((sample.sender_name, sample.sender_address))
        message["To"] = OFFICE_ADDRESS
        message["Date"] = format_datetime(SENT_AT)
        if sample.subject:
            message["Subject"] = sample.subject
        message.set_content(sample.body)
        if sample.attachment:
            self._attach(message, sample)
        return message

    def _attach(self, message: EmailMessage, sample: SampleEmail) -> None:
        if sample.attachment is None:
            return
        
        attachment = sample.attachment
        renderer = self._renderers[attachment.extension]
        message.add_attachment(
            renderer.render(attachment.lines),
            maintype=renderer.maintype,
            subtype=renderer.subtype,
            filename=attachment.filename,
        )


class SampleWriter:
    _columns = ["email_file", *(f.name for f in fields(Expected)), "expected_filename"]

    def __init__(self, builder: EmailBuilder, inbox_dir: Path, expected_csv: Path):
        self._builder = builder
        self._inbox_dir = inbox_dir
        self._expected_csv = expected_csv

    def write_all(self, samples: tuple[SampleEmail, ...]) -> None:
        self._prepare_inbox()
        rows = [self._write_email(sample) for sample in samples]
        self._write_expected(rows)

    def _prepare_inbox(self) -> None:
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        for old_file in self._inbox_dir.glob("*.eml"):
            old_file.unlink()

    def _write_email(self, sample: SampleEmail) -> dict[str, str]:
        filename = f"{sample.file_stem}.eml"
        (self._inbox_dir / filename).write_bytes(self._builder.build(sample).as_bytes())
        return {
            "email_file": filename,
            **asdict(sample.expected),
            "expected_filename": sample.expected_filename,
        }

    def _write_expected(self, rows: list[dict[str, str]]) -> None:
        self._expected_csv.parent.mkdir(parents=True, exist_ok=True)
        with self._expected_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=self._columns)
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    SampleWriter(EmailBuilder(RENDERERS), INBOX_DIR, EXPECTED_CSV).write_all(SAMPLES)
    print(f"Generated {len(SAMPLES)} emails in {INBOX_DIR} and {EXPECTED_CSV}")


if __name__ == "__main__":
    main()