from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentInfo(BaseModel):
    file_name: str
    file_type: str
    file_size_bytes: int | None = None
    sha256: str | None = None
    parser: str | None = None
    page_count: int | None = None
    parsed_at_utc: str


class ProfileLink(BaseModel):
    network: str
    url: str
    username: str | None = None


class ContactDetails(BaseModel):
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    location: str | None = None
    profile_links: list[ProfileLink] = Field(default_factory=list)


class CandidateCore(BaseModel):
    full_name: str | None = None
    headline: str | None = None
    summary: str | None = None
    contact: ContactDetails = Field(default_factory=ContactDetails)


class ExperienceItem(BaseModel):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    duration_months: int | None = None
    description: str | None = None
    highlights: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class EducationItem(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    grade: str | None = None
    description: str | None = None
    confidence: float = 0.0


class ProjectItem(BaseModel):
    name: str | None = None
    role: str | None = None
    description: str | None = None
    links: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class CertificationItem(BaseModel):
    name: str
    issuer: str | None = None
    date: str | None = None


class LanguageItem(BaseModel):
    name: str
    proficiency: str | None = None


class SkillInventory(BaseModel):
    programming_languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    cloud_platforms: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    data_and_ai: list[str] = Field(default_factory=list)
    devops_and_tools: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)
    other: list[str] = Field(default_factory=list)
    all: list[str] = Field(default_factory=list)


class ResumeSignals(BaseModel):
    total_experience_years: float | None = None
    seniority: str | None = None
    dominant_domains: list[str] = Field(default_factory=list)


class ExtractionQuality(BaseModel):
    completeness_score: float
    warnings: list[str] = Field(default_factory=list)


class ResumeProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "1.0.0"
    document: DocumentInfo
    candidate: CandidateCore
    skills: SkillInventory
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    languages: list[LanguageItem] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    sections: dict[str, str] = Field(default_factory=dict)
    raw_text: str
    signals: ResumeSignals
    quality: ExtractionQuality
    extras: dict[str, Any] = Field(default_factory=dict)
