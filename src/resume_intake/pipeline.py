from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from resume_intake.extractors import (
    build_quality,
    extract_achievements,
    extract_candidate,
    extract_certifications,
    extract_education,
    extract_experience,
    extract_languages,
    extract_projects,
    extract_skills,
    infer_signals,
    split_sections,
)
from resume_intake.parsers import get_parser
from resume_intake.schema import DocumentInfo, ResumeProfile
from resume_intake.utils import normalize_text, sha256_file

PostProcessor = Callable[[ResumeProfile], ResumeProfile]


def parse_resume_file(
    file_path: str | Path,
    post_processors: list[PostProcessor] | None = None,
) -> ResumeProfile:
    path = Path(file_path)
    parser = get_parser(path)
    parsed_document = parser.parse(path)

    stat = path.stat()
    document_info = DocumentInfo(
        file_name=path.name,
        file_type=path.suffix.lower().lstrip("."),
        file_size_bytes=stat.st_size,
        sha256=sha256_file(path),
        parser=parser.parser_name,
        page_count=parsed_document.metadata.get("page_count"),
        parsed_at_utc=datetime.now(timezone.utc).isoformat(),
    )

    return build_profile_from_text(
        parsed_document.text,
        document_info,
        post_processors=post_processors,
        extras={"parser_metadata": parsed_document.metadata},
    )


def build_profile_from_text(
    text: str,
    document_info: DocumentInfo,
    post_processors: list[PostProcessor] | None = None,
    extras: dict[str, object] | None = None,
) -> ResumeProfile:
    normalized_text = normalize_text(text)
    sections = split_sections(normalized_text)

    candidate = extract_candidate(normalized_text, sections)
    skills = extract_skills(normalized_text, sections)
    experience = extract_experience(sections)
    education = extract_education(sections)
    projects = extract_projects(sections)
    certifications = extract_certifications(sections)
    languages = extract_languages(sections)
    achievements = extract_achievements(sections)

    signals = infer_signals(experience, skills)
    quality = build_quality(normalized_text, candidate, skills, experience, education, projects)

    profile = ResumeProfile(
        document=document_info,
        candidate=candidate,
        skills=skills,
        experience=experience,
        education=education,
        projects=projects,
        certifications=certifications,
        languages=languages,
        achievements=achievements,
        sections=sections,
        raw_text=normalized_text,
        signals=signals,
        quality=quality,
        extras=extras or {},
    )

    for processor in post_processors or []:
        profile = processor(profile)

    return profile
