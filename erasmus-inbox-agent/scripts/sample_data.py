from dataclasses import dataclass
from pathlib import Path

ACTION_FILE = "file"
ACTION_FAQ = "answer_faq"
ACTION_ESCALATE = "escalate"

LEARNING_AGREEMENT = "LearningAgreement"
TRANSCRIPT = "Transcript"
INSURANCE = "Insurance"
CERTIFICATE_OF_ARRIVAL = "CertificateOfArrival"

ACADEMIC_YEAR = "2026-27"

@dataclass(frozen=True)
class Attachment:
    filename: str
    lines: tuple[str, ...]

    @property
    def extension(self) -> str:
        return Path(self.filename).suffix.lower()


@dataclass(frozen=True)
class Expected:
    action: str
    surname: str = ""
    name: str = ""
    doc_type: str = ""
    academic_year: str = ""
    host_university: str = ""
    start_date: str = ""
    end_date: str = ""


@dataclass(frozen=True)
class SampleEmail:
    file_stem: str
    sender_name: str
    sender_address: str
    subject: str
    body: str
    expected: Expected
    attachment: Attachment | None = None

    @property
    def expected_filename(self) -> str:
        if self.expected.action != ACTION_FILE or self.attachment is None:
            return ""
        e = self.expected
        return f"{e.surname}_{e.name}_{e.doc_type}_{e.academic_year}{self.attachment.extension}"


def _document(title: str, student: str | None, host: str, period: str) -> tuple[str, ...]:
    lines = (
        title,
        f"Student: {student}" if student else None,
        f"Host university: {host}",
        f"Period: {period}",
    )
    return tuple(line for line in lines if line)


SAMPLES: tuple[SampleEmail, ...] = (
    SampleEmail(
        file_stem="01_signed_learning_agreement",
        sender_name="Anna Kalnina",
        sender_address="anna.kalnina@student.example",
        subject="signed",
        body="Hi, here is the signed one.\nAnna",
        attachment=Attachment(
            "scan_0042.pdf",
            _document("LEARNING AGREEMENT", "Kalnina Anna", "TU Delft", "01 Feb 2027 - 30 Jun 2027"),
        ),
        expected=Expected(
            ACTION_FILE, "Kalnina", "Anna", LEARNING_AGREEMENT, ACADEMIC_YEAR,
            "TU Delft", "2027-02-01", "2027-06-30",
        ),
    ),
    SampleEmail(
        file_stem="02_no_subject_jpg_transcript",
        sender_name="Janis Berzins",
        sender_address="j.berzins@student.example",
        subject="",
        body="",
        attachment=Attachment(
            "IMG_2231.jpg",
            _document("TRANSCRIPT OF RECORDS", "Berzins Janis", "University of Vienna", "01 Sep 2026 - 31 Jan 2027"),
        ),
        expected=Expected(
            ACTION_FILE, "Berzins", "Janis", TRANSCRIPT, ACADEMIC_YEAR,
            "University of Vienna", "2026-09-01", "2027-01-31",
        ),
    ),
    SampleEmail(
        file_stem="03_insurance_vague_filename",
        sender_name="Maria Rossi",
        sender_address="maria.r@student.example",
        subject="insurance??",
        body="see attachment",
        attachment=Attachment(
            "document(3).pdf",
            _document("INSURANCE CERTIFICATE", "Rossi Maria", "Universidad de Salamanca", "15.09.2026 - 15.02.2027"),
        ),
        expected=Expected(
            ACTION_FILE, "Rossi", "Maria", INSURANCE, ACADEMIC_YEAR,
            "Universidad de Salamanca", "2026-09-15", "2027-02-15",
        ),
    ),
    SampleEmail(
        file_stem="04_certificate_of_arrival",
        sender_name="Lena Hoffmann",
        sender_address="lena.hoffmann@student.example",
        subject="Certificate of arrival - Lena Hoffmann",
        body=(
            "Dear office,\n\nI arrived in Espoo on 1 September. "
            "The certificate of arrival is attached.\n\nBest regards,\nLena Hoffmann"
        ),
        attachment=Attachment(
            "Certificate_of_Arrival.pdf",
            _document("CERTIFICATE OF ARRIVAL", "Lena Hoffmann", "Aalto University", "2026-09-01 - 2027-01-31"),
        ),
        expected=Expected(
            ACTION_FILE, "Hoffmann", "Lena", CERTIFICATE_OF_ARRIVAL, ACADEMIC_YEAR,
            "Aalto University", "2026-09-01", "2027-01-31",
        ),
    ),
    SampleEmail(
        file_stem="05_question_deadline",
        sender_name="Tom Walker",
        sender_address="tom.w@student.example",
        subject="When is the deadline?",
        body="Hello, when is the deadline for submitting the Learning Agreement? Thanks, Tom",
        expected=Expected(ACTION_FAQ),
    ),
    SampleEmail(
        file_stem="06_question_not_in_faq",
        sender_name="Sara Novak",
        sender_address="sara.n@student.example",
        subject="Question about my stay",
        body="Hello, can I extend my exchange by one more semester? Who should I ask? Sara Novak",
        expected=Expected(ACTION_ESCALATE),
    ),
    SampleEmail(
        file_stem="07_diacritics_name",
        sender_name="José Núñez",
        sender_address="jose.nunez@student.example",
        subject="Mi Learning Agreement",
        body="Hola! Here is my document for the spring semester.\nJosé",
        attachment=Attachment(
            "LA_final_v2.pdf",
            _document("LEARNING AGREEMENT", "José Núñez", "Politecnico di Milano", "15 Feb 2027 - 15 Jul 2027"),
        ),
        expected=Expected(
            ACTION_FILE, "Nunez", "Jose", LEARNING_AGREEMENT, ACADEMIC_YEAR,
            "Politecnico di Milano", "2027-02-15", "2027-07-15",
        ),
    ),
    SampleEmail(
        file_stem="08_name_only_in_body",
        sender_name="",
        sender_address="mk2001@student.example",
        subject="docs",
        body="Hello,\nthis is Katarzyna Wójcik, I am attaching my insurance. Is it ok?",
        attachment=Attachment(
            "scan.pdf",
            _document("INSURANCE CERTIFICATE", None, "University of Copenhagen", "01 Sep 2026 - 31 Jan 2027"),
        ),
        expected=Expected(
            ACTION_FILE, "Wojcik", "Katarzyna", INSURANCE, ACADEMIC_YEAR,
            "University of Copenhagen", "2026-09-01", "2027-01-31",
        ),
    ),
    SampleEmail(
        file_stem="09_second_document_same_student",
        sender_name="Anna Kalnina",
        sender_address="anna.kalnina@student.example",
        subject="insurance",
        body="Insurance for the same exchange, as requested.\nAnna",
        attachment=Attachment(
            "Policy.pdf",
            _document("INSURANCE CERTIFICATE", "Kalnina Anna", "TU Delft", "01 Feb 2027 - 30 Jun 2027"),
        ),
        expected=Expected(
            ACTION_FILE, "Kalnina", "Anna", INSURANCE, ACADEMIC_YEAR,
            "TU Delft", "2027-02-01", "2027-06-30",
        ),
    ),
    SampleEmail(
        file_stem="10_unreadable_scan",
        sender_name="",
        sender_address="scanner@student.example",
        subject="scan",
        body="",
        attachment=Attachment(
            "scan_0099.pdf",
            ("SCAN 0099", "[smudged, illegible]", "Student: ?????", "Period: ??/??/????"),
        ),
        expected=Expected(ACTION_ESCALATE),
    ),
)