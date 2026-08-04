from __future__ import annotations

from pathlib import Path

from resume_intake.parsers.base import ResumeParser
from resume_intake.parsers.docx_parser import DocxResumeParser
from resume_intake.parsers.pdf_parser import PdfResumeParser

_PARSERS: tuple[ResumeParser, ...] = (PdfResumeParser(), DocxResumeParser())


def get_parser(file_path: str | Path) -> ResumeParser:
    path = Path(file_path)
    suffix = path.suffix.lower()

    for parser in _PARSERS:
        if parser.supports(suffix):
            return parser

    supported = sorted({ext for parser in _PARSERS for ext in parser.supported_extensions})
    raise ValueError(
        f"Unsupported file extension '{suffix}'. Supported extensions: {', '.join(supported)}"
    )
