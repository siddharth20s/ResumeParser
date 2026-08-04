from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from resume_intake.parsers.base import ResumeParser
from resume_intake.types import ParsedDocument


class PdfResumeParser(ResumeParser):
    supported_extensions = (".pdf",)
    parser_name = "pypdf"

    def parse(self, file_path: Path) -> ParsedDocument:
        try:
            reader = PdfReader(str(file_path))
        except Exception as exc:
            raise ValueError(f"Unable to read PDF file: {file_path}") from exc

        page_text: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                page_text.append(text)

        return ParsedDocument(
            text="\n\n".join(page_text).strip(),
            metadata={"page_count": len(reader.pages)},
        )
