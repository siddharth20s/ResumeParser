from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from resume_intake.types import ParsedDocument


class ResumeParser(ABC):
    supported_extensions: tuple[str, ...] = ()
    parser_name: str = "base"

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.supported_extensions

    @abstractmethod
    def parse(self, file_path: Path) -> ParsedDocument:
        raise NotImplementedError
