from __future__ import annotations

import re
from datetime import date

from resume_intake.constants import SECTION_ALIASES, SKILL_CANONICAL_MAP, SKILL_TAXONOMY
from resume_intake.schema import (
    CandidateCore,
    CertificationItem,
    ContactDetails,
    EducationItem,
    ExperienceItem,
    ExtractionQuality,
    LanguageItem,
    ProfileLink,
    ProjectItem,
    ResumeSignals,
    SkillInventory,
)
from resume_intake.utils import clip_text, month_delta, parse_date_token, safe_ratio, to_iso_month, unique

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s)>,]+", re.IGNORECASE)
PROFILE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:linkedin\.com/(?:in|pub)/[A-Za-z0-9_.-]+|"
    r"github\.com/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*|leetcode\.com/[A-Za-z0-9_.-]+|"
    r"stackoverflow\.com/users/[A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")
BULLET_LINE_RE = re.compile(r"^[\-*\u2022]\s+")

_MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_TOKEN = rf"(?:{_MONTH_PATTERN}\s+\d{{4}}|(?:0?[1-9]|1[0-2])[/-]\d{{2,4}}|\d{{4}}|Present|Current|Now)"
DATE_RANGE_RE = re.compile(rf"(?P<start>{_DATE_TOKEN})\s*(?:-|to|\u2013|\u2014)\s*(?P<end>{_DATE_TOKEN})", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

_TITLE_HINTS = {
    "engineer",
    "developer",
    "manager",
    "analyst",
    "consultant",
    "intern",
    "scientist",
    "architect",
    "lead",
    "director",
    "specialist",
    "administrator",
    "officer",
}

_DEGREE_HINTS = {
    "b.e",
    "b.tech",
    "bachelor",
    "b.sc",
    "m.e",
    "m.tech",
    "master",
    "m.sc",
    "mba",
    "phd",
    "doctorate",
    "diploma",
}

_ALIAS_LOOKUP: dict[str, str] = {}
for section_name, aliases in SECTION_ALIASES.items():
    for alias in aliases:
        normalized = re.sub(r"\s+", " ", alias.strip().casefold())
        _ALIAS_LOOKUP[normalized] = section_name

_TEXT_INFERENCE_CATEGORIES_WHEN_SECTION_EXISTS = {"domain_keywords", "data_and_ai"}
_GENERIC_OTHER_SKILL_TOKENS = {
    "cloud",
    "security",
    "monitoring",
    "observability",
    "automation",
    "storage",
}


def split_sections(text: str) -> dict[str, str]:
    section_lines: dict[str, list[str]] = {name: [] for name in SECTION_ALIASES}
    section_lines["_unassigned"] = []

    current_section = "_unassigned"
    for raw_line in text.split("\n"):
        line = raw_line.strip()

        if not line:
            if section_lines[current_section] and section_lines[current_section][-1] != "":
                section_lines[current_section].append("")
            continue

        heading_match = _heading_to_section(line)
        if heading_match is not None and len(line) <= 70:
            current_section = heading_match
            continue

        section_lines[current_section].append(line)

    collapsed: dict[str, str] = {}
    for key, values in section_lines.items():
        text_value = "\n".join(values).strip()
        if text_value:
            collapsed[key] = text_value

    return collapsed


def extract_candidate(text: str, sections: dict[str, str]) -> CandidateCore:
    header_text = sections.get("_unassigned", "")
    top_lines = [line.strip() for line in header_text.splitlines() if line.strip()][:12]
    if not top_lines:
        top_lines = [line.strip() for line in text.splitlines() if line.strip()][:12]

    emails = unique([email.casefold() for email in EMAIL_RE.findall(text)])
    phones = _extract_phones(text)
    header_scope = "\n".join(top_lines)
    profile_links = _extract_profile_links(header_scope)
    if not profile_links:
        profile_links = _extract_profile_links(text)

    full_name = _guess_full_name(top_lines)
    summary = sections.get("summary") or ""
    headline = _guess_headline(top_lines, full_name, summary)
    if not summary:
        summary = _fallback_summary(top_lines, full_name, headline)

    location = _guess_location(top_lines)

    return CandidateCore(
        full_name=full_name,
        headline=headline,
        summary=clip_text(summary, 1800) if summary else None,
        contact=ContactDetails(
            emails=emails,
            phones=phones,
            location=location,
            profile_links=profile_links,
        ),
    )


def extract_skills(text: str, sections: dict[str, str]) -> SkillInventory:
    lowered = text.casefold()
    skills_section_text = sections.get("skills", "")
    section_tokens = [_canonicalize_skill(token) for token in _parse_skills_section_tokens(skills_section_text)]
    section_tokens = unique([token for token in section_tokens if token])

    categorized: dict[str, list[str]] = {category: [] for category in SKILL_TAXONOMY}
    taxonomy_hits: list[str] = []
    other_candidates: list[str] = []

    for token in section_tokens:
        category = _category_for_skill(token)
        if category is None:
            if _is_specific_other_skill(token):
                other_candidates.append(token)
            continue
        categorized[category].append(token)
        taxonomy_hits.append(token)

    if not section_tokens:
        for category, keywords in SKILL_TAXONOMY.items():
            for keyword in keywords:
                if _contains_keyword(lowered, keyword):
                    canonical = _canonicalize_skill(keyword)
                    categorized[category].append(canonical)
                    taxonomy_hits.append(canonical)
    else:
        inference_text = "\n".join(
            [
                sections.get("summary", ""),
                sections.get("experience", ""),
                sections.get("projects", ""),
            ]
        ).casefold()
        for category in _TEXT_INFERENCE_CATEGORIES_WHEN_SECTION_EXISTS:
            for keyword in SKILL_TAXONOMY.get(category, []):
                canonical = _canonicalize_skill(keyword)
                if canonical in categorized[category]:
                    continue
                min_hits = 1 if category == "domain_keywords" else 2
                if _keyword_occurrences(inference_text, keyword) >= min_hits:
                    categorized[category].append(canonical)
                    taxonomy_hits.append(canonical)

    for category in categorized:
        categorized[category] = unique(categorized[category])
    taxonomy_hits = unique(taxonomy_hits)

    known_lookup = {skill.casefold() for skill in taxonomy_hits}
    other_skills = [token for token in other_candidates if token.casefold() not in known_lookup]
    other_skills = unique([token for token in other_skills if _is_specific_other_skill(token)])
    all_skills = unique(taxonomy_hits + other_skills)

    return SkillInventory(
        programming_languages=categorized.get("programming_languages", []),
        frameworks=categorized.get("frameworks", []),
        cloud_platforms=categorized.get("cloud_platforms", []),
        databases=categorized.get("databases", []),
        data_and_ai=categorized.get("data_and_ai", []),
        devops_and_tools=categorized.get("devops_and_tools", []),
        soft_skills=categorized.get("soft_skills", []),
        domain_keywords=categorized.get("domain_keywords", []),
        other=unique(other_skills),
        all=all_skills,
    )


def extract_experience(sections: dict[str, str]) -> list[ExperienceItem]:
    section_text = sections.get("experience", "")
    if not section_text:
        return []

    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    stateful_items = _extract_experience_stateful(lines)
    if stateful_items:
        return stateful_items

    blocks = _split_blocks(section_text)
    items: list[ExperienceItem] = []

    for block in blocks[:25]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        header = lines[0]
        title, company = _extract_company_title(header)
        start_date, end_date, is_current, duration_months = _extract_date_info(block)
        location = _extract_location_from_block(lines)
        technologies = _find_skills_in_text(block)
        highlights = _extract_highlights(block)

        description_lines = lines[1:] if len(lines) > 1 else []
        description = clip_text(" ".join(description_lines), 1800) if description_lines else None

        confidence = _confidence_score(
            has_company=bool(company),
            has_title=bool(title),
            has_dates=bool(start_date or end_date),
            has_description=bool(description),
            has_technologies=bool(technologies),
        )

        items.append(
            ExperienceItem(
                company=company,
                title=title,
                location=location,
                start_date=start_date,
                end_date=end_date,
                is_current=is_current,
                duration_months=duration_months,
                description=description,
                highlights=highlights,
                technologies=technologies,
                confidence=confidence,
            )
        )

    return items


def extract_education(sections: dict[str, str]) -> list[EducationItem]:
    section_text = sections.get("education", "")
    if not section_text:
        return []

    blocks = _split_blocks(section_text)
    items: list[EducationItem] = []

    for block in blocks[:15]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        institution = _extract_institution(lines)
        degree = _extract_degree(lines)
        field_of_study = _extract_field_of_study(block)
        grade = _extract_grade(block)
        start_date, end_date, _, _ = _extract_date_info(block)
        if end_date is None:
            end_date = _extract_graduation_end_date(block)
        description = clip_text(" ".join(lines[1:]), 1200) if len(lines) > 1 else None

        confidence = _confidence_score(
            has_company=bool(institution),
            has_title=bool(degree),
            has_dates=bool(start_date or end_date),
            has_description=bool(description),
            has_technologies=False,
        )

        items.append(
            EducationItem(
                institution=institution,
                degree=degree,
                field_of_study=field_of_study,
                start_date=start_date,
                end_date=end_date,
                grade=grade,
                description=description,
                confidence=confidence,
            )
        )

    return items


def extract_projects(sections: dict[str, str]) -> list[ProjectItem]:
    section_text = sections.get("projects", "")
    if not section_text:
        return []

    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    stateful_projects = _extract_projects_stateful(lines)
    if stateful_projects:
        return stateful_projects

    blocks = _split_blocks(section_text)
    projects: list[ProjectItem] = []

    for block in blocks[:20]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        first_line = lines[0]
        if "|" in first_line:
            parts = [part.strip() for part in first_line.split("|", 1)]
            name = parts[0]
            role = parts[1] if len(parts) > 1 else None
        else:
            name = first_line
            role = None

        links = _extract_links(block)
        technologies = _find_skills_in_text(block)
        description = clip_text(" ".join(lines[1:]), 1600) if len(lines) > 1 else None

        projects.append(
            ProjectItem(
                name=name,
                role=role,
                description=description,
                links=links,
                technologies=technologies,
            )
        )

    return projects


def extract_certifications(sections: dict[str, str]) -> list[CertificationItem]:
    section_text = sections.get("certifications", "")
    if not section_text:
        return []

    lines = [
        re.sub(r"^[\-*\u2022\s]+", "", line).strip()
        for line in section_text.splitlines()
        if line.strip()
    ]

    certifications: list[CertificationItem] = []
    for line in lines:
        if not line:
            continue

        issuer = None
        name = line

        by_split = re.split(r"\s+by\s+", line, maxsplit=1, flags=re.IGNORECASE)
        if len(by_split) == 2:
            name = by_split[0].strip(" -|")
            issuer = by_split[1].strip(" -|")

        certifications.append(CertificationItem(name=name, issuer=issuer))

    return certifications


def extract_languages(sections: dict[str, str]) -> list[LanguageItem]:
    section_text = sections.get("languages", "")
    if not section_text:
        return []

    chunks = re.split(r"[,;\n]", section_text)
    items: list[LanguageItem] = []

    for chunk in chunks:
        token = re.sub(r"^[\-*\u2022\s]+", "", chunk).strip()
        if not token:
            continue

        match = re.match(r"^(?P<name>[A-Za-z ]+?)(?:\s*[(-]\s*(?P<level>[^)\]]+)\s*[)\]])?$", token)
        if match:
            name = match.group("name").strip()
            level = (match.group("level") or "").strip() or None
        else:
            name = token
            level = None

        if len(name) > 1:
            items.append(LanguageItem(name=name, proficiency=level))

    return items


def extract_achievements(sections: dict[str, str]) -> list[str]:
    section_text = sections.get("achievements", "")
    if not section_text:
        return []

    lines = [
        re.sub(r"^[\-*\u2022\s]+", "", line).strip()
        for line in section_text.splitlines()
        if line.strip()
    ]
    return unique([line for line in lines if len(line) > 2])


def infer_signals(experience: list[ExperienceItem], skills: SkillInventory) -> ResumeSignals:
    total_months = 0
    for item in experience:
        if item.duration_months is not None:
            total_months += item.duration_months

    years = round(total_months / 12.0, 1) if total_months > 0 else None
    seniority = _infer_seniority(years)

    domain_scores = {
        "application_development": len(set(skills.programming_languages + skills.frameworks)),
        "cloud_and_devops": len(set(skills.cloud_platforms + skills.devops_and_tools)),
        "data_and_ai": len(set(skills.data_and_ai)),
        "domain_specialization": len(set(skills.domain_keywords)),
    }

    ranked = sorted(domain_scores.items(), key=lambda pair: pair[1], reverse=True)
    dominant_domains = [label for label, score in ranked if score > 0][:3]

    return ResumeSignals(
        total_experience_years=years,
        seniority=seniority,
        dominant_domains=dominant_domains,
    )


def build_quality(
    raw_text: str,
    candidate: CandidateCore,
    skills: SkillInventory,
    experience: list[ExperienceItem],
    education: list[EducationItem],
    projects: list[ProjectItem],
) -> ExtractionQuality:
    checks = {
        "name": bool(candidate.full_name),
        "contact": bool(candidate.contact.emails or candidate.contact.phones),
        "summary": bool(candidate.summary),
        "skills": bool(skills.all),
        "experience": bool(experience),
        "education": bool(education),
    }

    coverage_score = safe_ratio(sum(checks.values()), len(checks))
    structure_score = _structure_confidence_score(experience, education)
    signal_score = _signal_quality_score(candidate, skills)

    score = round((0.5 * coverage_score) + (0.3 * structure_score) + (0.2 * signal_score), 3)
    penalty = 0.0
    warnings: list[str] = []
    raw_lower = raw_text.casefold()

    if not raw_text.strip():
        warnings.append("No text extracted from resume. For scanned PDFs, run OCR first.")
    if not checks["contact"]:
        warnings.append("Contact details were not reliably detected.")
    if not checks["experience"]:
        warnings.append("Work experience section not found or could not be parsed.")
    if ("linkedin.com" in raw_lower or "github.com" in raw_lower) and not candidate.contact.profile_links:
        warnings.append("Social profile links appear in raw text but were not extracted.")
        penalty += 0.08

    if candidate.headline and len(candidate.headline.split()) > 16:
        warnings.append("Headline appears noisy; extracted text may include summary spillover.")
        penalty += 0.08

    low_conf_count = len([item for item in experience if item.confidence < 0.65])
    if low_conf_count:
        warnings.append("Some experience items have low confidence and may need normalization.")
        penalty += min(0.2, 0.06 * low_conf_count)

    if any(item.company is None or item.title is None for item in experience):
        penalty += 0.06

    if any((project.name or "").lstrip().startswith("•") for project in projects):
        warnings.append("Project segmentation may be noisy for bullet-based resumes.")
        penalty += 0.08

    if len(skills.all) > 70 or (len(skills.all) > 55 and len(skills.other) > 12):
        warnings.append("Skill inventory is very broad; review possible over-tagging.")
        penalty += 0.05

    if len(skills.other) > 18:
        warnings.append("Many uncategorized skills detected; taxonomy tuning may improve precision.")
        penalty += 0.04

    if score < 0.5:
        warnings.append("Low completeness score; consider section heading normalization.")

    score = min(score, 0.95)
    score = max(0.0, round(score - penalty, 3))
    return ExtractionQuality(completeness_score=score, warnings=warnings)


def _heading_to_section(line: str) -> str | None:
    normalized = re.sub(r"\s+", " ", line.strip().strip(":").strip("- ")).casefold()
    normalized = re.sub(r"[^a-z\s]", "", normalized).strip()
    if not normalized:
        return None

    if normalized in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[normalized]

    # Allow short heading variants like "Work Experience -"
    for alias, section in _ALIAS_LOOKUP.items():
        if normalized.startswith(alias) and len(normalized.split()) <= 5:
            return section

    return None


def _extract_phones(text: str) -> list[str]:
    phones: list[str] = []
    for match in PHONE_RE.findall(text):
        digits = re.sub(r"\D", "", match)
        if len(digits) < 10 or len(digits) > 15:
            continue
        if match.strip().startswith("+"):
            normalized = "+" + digits
        else:
            normalized = digits
        phones.append(normalized)
    return unique(phones)


def _extract_profile_links(text: str) -> list[ProfileLink]:
    links = _extract_links(text)
    output: list[ProfileLink] = []

    for url in links:
        lowered = url.casefold()
        network = "portfolio"
        username = None

        if "linkedin.com" in lowered:
            network = "linkedin"
            user_match = re.search(r"linkedin\.com/(?:in|pub)/([^/?#]+)", lowered)
            username = user_match.group(1) if user_match else None
        elif "github.com" in lowered:
            network = "github"
            user_match = re.search(r"github\.com/([^/?#]+)", lowered)
            username = user_match.group(1) if user_match else None
        elif "leetcode.com" in lowered:
            network = "leetcode"
            user_match = re.search(r"leetcode\.com/([^/?#]+)", lowered)
            username = user_match.group(1) if user_match else None
        elif "stackoverflow.com" in lowered:
            network = "stackoverflow"

        output.append(ProfileLink(network=network, url=url, username=username))

    return output


def _extract_links(text: str) -> list[str]:
    raw_links: list[str] = []
    raw_links.extend(URL_RE.findall(text))
    raw_links.extend(PROFILE_RE.findall(text))

    normalized: list[str] = []
    for raw in raw_links:
        cleaned = _normalize_link(raw)
        if cleaned:
            normalized.append(cleaned)

    return unique(normalized)


def _normalize_link(link: str) -> str | None:
    cleaned = link.strip().rstrip(").,; ")
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        return None

    lowered = cleaned.casefold()
    if lowered.startswith("www."):
        return "https://" + cleaned
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return cleaned
    return "https://" + cleaned


def _guess_full_name(lines: list[str]) -> str | None:
    reserved = set(_ALIAS_LOOKUP.keys()) | {"resume", "curriculum vitae", "cv"}

    for line in lines[:6]:
        if "@" in line or "http" in line.casefold():
            continue

        compact = re.sub(r"[^A-Za-z .'-]", "", line).strip()
        if not compact or any(char.isdigit() for char in compact):
            continue

        words = [word for word in compact.split() if word]
        if len(words) < 2 or len(words) > 5:
            continue

        if compact.casefold() in reserved:
            continue

        uppercase_words = sum(1 for word in words if word[:1].isupper())
        if uppercase_words >= max(1, len(words) - 1):
            return " ".join(words)

    return None


def _guess_headline(lines: list[str], full_name: str | None, summary: str) -> str | None:
    for line in lines:
        if full_name and line == full_name:
            continue
        lowered = line.casefold()
        if "@" in line or "http" in lowered or "linkedin.com" in lowered or "github.com" in lowered:
            continue
        if _heading_to_section(line) is not None:
            continue
        if re.search(r"\d{7,}", re.sub(r"\D", "", line)):
            continue
        if "❖" in line or "|" in line:
            continue

        if 3 <= len(line.split()) <= 8 and _title_score(line) > 0:
            return line

    first_sentence = re.split(r"[.!?\n]", summary, maxsplit=1)[0].strip()
    if first_sentence:
        match = re.match(r"(?P<title>[A-Za-z0-9&/+ .-]{3,90}?)\s+with\b", first_sentence, re.IGNORECASE)
        if match:
            return match.group("title").strip(" -|")

    return None


def _fallback_summary(lines: list[str], full_name: str | None, headline: str | None) -> str:
    ignored = {full_name or "", headline or ""}
    summary_lines: list[str] = []
    for line in lines:
        if line in ignored:
            continue
        if "@" in line or "http" in line.casefold():
            continue
        if _heading_to_section(line):
            continue
        summary_lines.append(line)
        if len(" ".join(summary_lines)) > 300:
            break
    return " ".join(summary_lines).strip()


def _guess_location(lines: list[str]) -> str | None:
    for line in lines[:5]:
        if "❖" in line or "|" in line:
            parts = [part.strip() for part in re.split(r"[❖|]", line) if part.strip()]
            for part in reversed(parts):
                if _is_location_token(part):
                    return part

    for line in lines:
        if _is_location_token(line):
            return line

        tail_match = re.search(r"([A-Za-z .'-]+,\s*[A-Za-z .'-]+)$", line)
        if tail_match:
            candidate = tail_match.group(1).strip()
            if _is_location_token(candidate):
                return candidate

    return None


def _contains_keyword(text_lower: str, keyword: str) -> bool:
    return _keyword_occurrences(text_lower, keyword) > 0


def _keyword_occurrences(text_lower: str, keyword: str) -> int:
    escaped = re.escape(keyword.casefold()).replace(r"\ ", r"\s+")
    pattern = r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])"
    return len(re.findall(pattern, text_lower))


def _parse_skills_section_tokens(section_text: str) -> list[str]:
    if not section_text:
        return []

    tokens: list[str] = []
    for raw_line in section_text.splitlines():
        line = re.sub(r"^[\-*\u2022\s]+", "", raw_line).strip()
        if not line:
            continue

        value_part = line.split(":", maxsplit=1)[1] if ":" in line else line

        for chunk in re.split(r"[·;|]", value_part):
            chunk = chunk.strip()
            if not chunk:
                continue
            expanded = _expand_skill_chunk(chunk)
            for token in expanded:
                cleaned = _clean_skill_token(token)
                if cleaned:
                    tokens.append(cleaned.casefold())

    return unique(tokens)


def _expand_skill_chunk(chunk: str) -> list[str]:
    expanded: list[str] = []

    match = re.match(r"^(?P<base>[A-Za-z0-9+.#/&' -]{2,})\((?P<inner>[^)]+)\)$", chunk)
    if match:
        base = match.group("base").strip()
        inner = match.group("inner").strip()
        if base:
            expanded.append(base)
        expanded.extend([part.strip() for part in re.split(r"[,/]", inner) if part.strip()])
        return expanded

    expanded.extend([part.strip() for part in re.split(r",", chunk) if part.strip()])
    return expanded


def _clean_skill_token(token: str) -> str:
    clean = re.sub(r"\s+", " ", token).strip().strip(":")
    clean = clean.strip("()")
    clean = clean.strip(" -")

    if not clean:
        return ""
    if len(clean) > 48:
        return ""
    if re.fullmatch(r"[0-9./]+", clean):
        return ""
    if clean.casefold() in {"cloud", "iac & config", "containers & orchestration", "ci/cd & automation"}:
        return ""

    return clean


def _canonicalize_skill(token: str) -> str:
    normalized = re.sub(r"\s+", " ", token.strip().casefold())
    normalized = SKILL_CANONICAL_MAP.get(normalized, normalized)
    normalized = SKILL_CANONICAL_MAP.get(normalized.replace("-", " "), normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _category_for_skill(token: str) -> str | None:
    for category, keywords in SKILL_TAXONOMY.items():
        for keyword in keywords:
            if _canonicalize_skill(keyword) == token:
                return category
    return None


def _is_specific_other_skill(token: str) -> bool:
    normalized = token.strip().casefold()
    if not normalized:
        return False
    if normalized in _GENERIC_OTHER_SKILL_TOKENS:
        return False
    if normalized.endswith("best practices"):
        return False
    if len(normalized) < 3:
        return False
    return True


def _split_blocks(section_text: str) -> list[str]:
    blocks = [value.strip() for value in re.split(r"\n\s*\n", section_text) if value.strip()]
    if len(blocks) > 1:
        return blocks

    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    if len(lines) <= 3:
        return [section_text.strip()] if section_text.strip() else []

    generated: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if current and _looks_like_new_entry(line):
            generated.append(current)
            current = []
        current.append(line)

    if current:
        generated.append(current)

    if len(generated) > 1:
        return ["\n".join(group) for group in generated]

    return [section_text.strip()]


def _looks_like_new_entry(line: str) -> bool:
    if DATE_RANGE_RE.search(line):
        return True
    if YEAR_RE.search(line) and (" - " in line or " at " in line.casefold() or "|" in line):
        return True
    return False


def _extract_experience_stateful(lines: list[str]) -> list[ExperienceItem]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in lines:
        if _is_experience_header_line(line):
            if current is not None:
                entries.append(current)
            current = {"header": line, "role_line": None, "content": []}
            continue

        if current is None:
            continue

        role_line = current.get("role_line")
        if role_line is None and not BULLET_LINE_RE.match(line):
            current["role_line"] = line
        else:
            content = current.get("content")
            if isinstance(content, list):
                content.append(line)

    if current is not None:
        entries.append(current)

    items: list[ExperienceItem] = []
    for entry in entries:
        item = _build_experience_item(entry)
        if item is not None:
            items.append(item)

    return items


def _is_experience_header_line(line: str) -> bool:
    if BULLET_LINE_RE.match(line):
        return False
    if DATE_RANGE_RE.search(line) is None:
        return False
    if len(line) > 140:
        return False

    company_hint = _strip_date_range(line)
    return bool(company_hint)


def _build_experience_item(entry: dict[str, object]) -> ExperienceItem | None:
    header = str(entry.get("header", "")).strip()
    if not header:
        return None

    role_line = str(entry.get("role_line") or "").strip()
    content_raw = entry.get("content")
    content_lines = [str(value).strip() for value in content_raw] if isinstance(content_raw, list) else []
    content_lines = [line for line in content_lines if line]

    company = _strip_date_range(header) or None
    start_date, end_date, is_current, duration_months = _extract_date_info(header)

    title, role_location = _parse_role_and_location(role_line)
    fallback_location = _extract_location_from_lines(content_lines[:4])
    location = role_location or fallback_location

    combined_lines = [header]
    if role_line:
        combined_lines.append(role_line)
    combined_lines.extend(content_lines)
    combined_text = "\n".join(combined_lines)

    highlights = _extract_highlights_from_lines(content_lines)
    description_parts: list[str] = []
    if highlights:
        description_parts.extend(highlights[:4])
    else:
        if role_line and role_line != location and role_line != (title or ""):
            description_parts.append(role_line)
        description_parts.extend([line for line in content_lines if not BULLET_LINE_RE.match(line)])

    description = clip_text(" ".join(description_parts), 1800) if description_parts else None
    technologies = _find_skills_in_text(combined_text)

    confidence = _confidence_score(
        has_company=bool(company),
        has_title=bool(title),
        has_dates=bool(start_date or end_date),
        has_description=bool(description or highlights),
        has_technologies=bool(technologies),
    )

    return ExperienceItem(
        company=company,
        title=title,
        location=location,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
        duration_months=duration_months,
        description=description,
        highlights=highlights,
        technologies=technologies,
        confidence=confidence,
    )


def _parse_role_and_location(line: str) -> tuple[str | None, str | None]:
    value = line.strip(" -|")
    if not value:
        return None, None

    if "," in value:
        left, right = [part.strip() for part in value.rsplit(",", 1)]
        if left and right:
            words = left.split()
            for count in range(1, min(3, len(words)) + 1):
                city = " ".join(words[-count:])
                location = f"{city}, {right}".strip()
                title_candidate = " ".join(words[:-count]).strip()
                if not title_candidate:
                    continue
                if _is_location_token(location):
                    return title_candidate.strip(" -|"), location

    if "|" in value:
        left, right = [part.strip() for part in value.split("|", 1)]
        if _is_location_token(right):
            return left or None, right

    tail_match = re.search(
        r"(?P<title>.+?)\s+(?P<city>[A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,2}),\s*(?P<country>[A-Za-z.'-]+(?:\s+[A-Za-z.'-]+){0,2})$",
        value,
    )
    if tail_match:
        candidate_location = f"{tail_match.group('city')}, {tail_match.group('country')}".strip()
        if _is_location_token(candidate_location):
            title = tail_match.group("title").strip(" -|")
            return title or None, candidate_location

    return value, None


def _extract_projects_stateful(lines: list[str]) -> list[ProjectItem]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in lines:
        if _is_project_header_line(line):
            if current is not None:
                entries.append(current)
            current = {"header": line, "stack_lines": [], "body": []}
            continue

        if current is None:
            continue

        body = current.get("body")
        stack_lines = current.get("stack_lines")
        if isinstance(body, list) and isinstance(stack_lines, list):
            if not body and _looks_like_tech_stack_line(line):
                stack_lines.append(line)
            else:
                body.append(line)

    if current is not None:
        entries.append(current)

    projects: list[ProjectItem] = []
    for entry in entries:
        project = _build_project_item(entry)
        if project is not None:
            projects.append(project)

    return projects


def _is_project_header_line(line: str) -> bool:
    if BULLET_LINE_RE.match(line):
        return False
    if DATE_RANGE_RE.search(line) is None:
        return False
    return len(line.split()) >= 3


def _looks_like_tech_stack_line(line: str) -> bool:
    if BULLET_LINE_RE.match(line):
        return False
    if len(line) > 220:
        return False
    if "·" in line or "|" in line:
        return True

    keyword_hits = len(_find_skills_in_text(line))
    return keyword_hits >= 2


def _build_project_item(entry: dict[str, object]) -> ProjectItem | None:
    header = str(entry.get("header", "")).strip()
    if not header:
        return None

    stack_raw = entry.get("stack_lines")
    body_raw = entry.get("body")
    stack_lines = [str(value).strip() for value in stack_raw] if isinstance(stack_raw, list) else []
    body_lines = [str(value).strip() for value in body_raw] if isinstance(body_raw, list) else []
    stack_lines = [line for line in stack_lines if line]
    body_lines = [line for line in body_lines if line]

    name = _strip_date_range(header) or header
    combined_text = "\n".join([name, *stack_lines, *body_lines]).strip()
    links = _extract_links(combined_text)
    technologies = _find_skills_in_text(combined_text)

    bullet_points = _extract_highlights_from_lines(body_lines)
    plain_body = [line for line in body_lines if not BULLET_LINE_RE.match(line)]
    description_parts: list[str] = []
    description_parts.extend(stack_lines)
    description_parts.extend(bullet_points)
    if not bullet_points:
        description_parts.extend(plain_body)
    description = clip_text(" ".join(description_parts), 1600) if description_parts else None

    return ProjectItem(
        name=name,
        role=None,
        description=description,
        links=links,
        technologies=technologies,
    )


def _extract_highlights_from_lines(lines: list[str]) -> list[str]:
    highlights: list[str] = []
    for line in lines:
        if BULLET_LINE_RE.match(line):
            cleaned = re.sub(r"^[\-*\u2022\s]+", "", line).strip()
            if cleaned:
                highlights.append(cleaned)
            continue

        if highlights:
            continuation = line.strip()
            if continuation and not _is_project_header_line(continuation) and not _is_experience_header_line(continuation):
                highlights[-1] = f"{highlights[-1]} {continuation}".strip()

    return unique(highlights)[:10]


def _strip_date_range(value: str) -> str:
    stripped = DATE_RANGE_RE.sub("", value)
    stripped = re.sub(r"\s{2,}", " ", stripped)
    return stripped.strip(" -|,")


def _extract_location_from_lines(lines: list[str]) -> str | None:
    for line in lines:
        if _is_location_token(line):
            return line

        tail_match = re.search(r"([A-Za-z .'-]+,\s*[A-Za-z .'-]+)$", line)
        if tail_match:
            candidate = tail_match.group(1).strip()
            if _is_location_token(candidate):
                return candidate

    return None


def _is_location_token(value: str) -> bool:
    token = value.strip()
    lowered = token.casefold()

    if not token or "," not in token:
        return False
    if any(char.isdigit() for char in token):
        return False
    if "@" in token or "http" in lowered or "linkedin.com" in lowered or "github.com" in lowered:
        return False
    if len(token.split()) > 8:
        return False
    if any(hint in lowered for hint in _TITLE_HINTS):
        return False

    return True


def _extract_company_title(header: str) -> tuple[str | None, str | None]:
    line = header.strip(" -|")

    if "|" in line:
        left, right = [part.strip() for part in line.split("|", 1)]
        return _assign_title_company(left, right)

    at_match = re.split(r"\bat\b", line, maxsplit=1, flags=re.IGNORECASE)
    if len(at_match) == 2:
        title = at_match[0].strip(" -|")
        company = at_match[1].strip(" -|")
        if title and company:
            return title, company

    if " - " in line:
        left, right = [part.strip() for part in line.split(" - ", 1)]
        return _assign_title_company(left, right)

    if "," in line:
        left, right = [part.strip() for part in line.split(",", 1)]
        return _assign_title_company(left, right)

    return None, None


def _assign_title_company(left: str, right: str) -> tuple[str | None, str | None]:
    left_score = _title_score(left)
    right_score = _title_score(right)

    if left_score == right_score:
        return left, right

    if left_score > right_score:
        return left, right

    return right, left


def _title_score(value: str) -> int:
    lowered = value.casefold()
    return sum(1 for hint in _TITLE_HINTS if hint in lowered)


def _extract_date_info(block: str) -> tuple[str | None, str | None, bool, int | None]:
    match = DATE_RANGE_RE.search(block)

    if match:
        start_token = match.group("start")
        end_token = match.group("end")
        is_current = end_token.casefold() in {"present", "current", "now"}

        start_date = parse_date_token(start_token)
        end_date = date.today() if is_current else parse_date_token(end_token)

        return (
            to_iso_month(start_date),
            "present" if is_current else to_iso_month(end_date),
            is_current,
            month_delta(start_date, end_date),
        )

    years = [token for token in YEAR_RE.findall(block)]
    if len(years) >= 2:
        start_year = parse_date_token(years[0])
        end_year = parse_date_token(years[1])
        return to_iso_month(start_year), to_iso_month(end_year), False, month_delta(start_year, end_year)

    return None, None, False, None


def _extract_location_from_block(lines: list[str]) -> str | None:
    return _extract_location_from_lines(lines[1:4])


def _extract_highlights(block: str) -> list[str]:
    highlights: list[str] = []
    for line in block.splitlines():
        if BULLET_LINE_RE.match(line.strip()):
            cleaned = re.sub(r"^[\-*\u2022\s]+", "", line).strip()
            if cleaned:
                highlights.append(cleaned)
    return unique(highlights)[:8]


def _find_skills_in_text(text: str) -> list[str]:
    lowered = text.casefold()
    found: list[str] = []
    for keywords in SKILL_TAXONOMY.values():
        for keyword in keywords:
            if _contains_keyword(lowered, keyword):
                found.append(_canonicalize_skill(keyword))
    return unique(found)


def _structure_confidence_score(experience: list[ExperienceItem], education: list[EducationItem]) -> float:
    if experience:
        exp_avg = sum(item.confidence for item in experience) / len(experience)
    else:
        exp_avg = 0.55

    if education:
        edu_avg = sum(item.confidence for item in education) / len(education)
    else:
        edu_avg = 0.55

    return round((0.75 * exp_avg) + (0.25 * edu_avg), 3)


def _signal_quality_score(candidate: CandidateCore, skills: SkillInventory) -> float:
    contact_points = 0
    contact_points += 1 if candidate.contact.emails else 0
    contact_points += 1 if candidate.contact.phones else 0
    contact_points += 1 if candidate.contact.profile_links else 0
    contact_points += 1 if candidate.contact.location else 0
    contact_score = contact_points / 4.0

    skill_count = len(skills.all)
    if skill_count == 0:
        skill_score = 0.0
    elif skill_count < 10:
        skill_score = 0.6
    elif skill_count <= 55:
        skill_score = 1.0
    elif skill_count <= 70:
        skill_score = 0.9
    else:
        skill_score = 0.78

    return round((0.55 * contact_score) + (0.45 * skill_score), 3)


def _extract_institution(lines: list[str]) -> str | None:
    hints = {"university", "college", "school", "institute", "academy"}
    for line in lines:
        lowered = line.casefold()
        if any(hint in lowered for hint in hints):
            return line
    return lines[0] if lines else None


def _extract_degree(lines: list[str]) -> str | None:
    for line in lines:
        lowered = line.casefold()
        if any(hint in lowered for hint in _DEGREE_HINTS):
            return line
    return None


def _extract_field_of_study(block: str) -> str | None:
    match = re.search(r"\b(?:in|major in|specialization in)\s+([A-Za-z&/ .-]+)", block, re.IGNORECASE)
    if match:
        value = match.group(1).strip(" .-")
        value = re.sub(r"\b(?:cgpa|gpa|grade)\b.*$", "", value, flags=re.IGNORECASE).strip(" .-")
        return value or None
    return None


def _extract_graduation_end_date(block: str) -> str | None:
    match = re.search(r"\bgraduated\s+((?:19|20)\d{2})\b", block, re.IGNORECASE)
    if match:
        parsed = parse_date_token(match.group(1))
        return to_iso_month(parsed)
    return None


def _extract_grade(block: str) -> str | None:
    match = re.search(r"\b(?:gpa|cgpa|grade)\s*[:\-]?\s*([A-Za-z0-9./]+)", block, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _confidence_score(
    has_company: bool,
    has_title: bool,
    has_dates: bool,
    has_description: bool,
    has_technologies: bool,
) -> float:
    score = 0.2
    score += 0.2 if has_company else 0.0
    score += 0.2 if has_title else 0.0
    score += 0.2 if has_dates else 0.0
    score += 0.1 if has_description else 0.0
    score += 0.1 if has_technologies else 0.0
    return round(min(score, 1.0), 2)


def _infer_seniority(years: float | None) -> str | None:
    if years is None:
        return None
    if years >= 12:
        return "principal"
    if years >= 8:
        return "senior"
    if years >= 4:
        return "mid"
    if years >= 1:
        return "junior"
    return "entry"
