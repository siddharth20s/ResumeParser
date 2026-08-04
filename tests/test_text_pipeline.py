from resume_intake.pipeline import build_profile_from_text
from resume_intake.schema import DocumentInfo


def test_build_profile_from_text_extracts_core_fields() -> None:
    sample_text = """
John Doe
Senior Data Engineer
john.doe@example.com | +1 (555) 123-9876
Bengaluru, India
https://www.linkedin.com/in/johndoe

SUMMARY
Data engineer with 7+ years experience building data platforms.

WORK EXPERIENCE
Senior Data Engineer | Acme Analytics
Jan 2020 - Present
- Built scalable ETL pipelines on AWS and Spark.
- Improved dashboard latency by 35%.

Data Engineer | Contoso Labs
Jun 2017 - Dec 2019
- Built APIs with Python and FastAPI.

EDUCATION
B.Tech in Computer Science, National Institute of Technology
2013 - 2017

SKILLS
Python, SQL, AWS, Spark, FastAPI, Docker, Kubernetes

PROJECTS
Hiring Intelligence Platform
Built matching service for candidate-job recommendations.
""".strip()

    document_info = DocumentInfo(
        file_name="sample.txt",
        file_type="txt",
        parsed_at_utc="2026-01-01T00:00:00+00:00",
    )

    profile = build_profile_from_text(sample_text, document_info)

    assert profile.candidate.full_name == "John Doe"
    assert "john.doe@example.com" in profile.candidate.contact.emails
    assert profile.experience
    assert profile.education
    assert "python" in profile.skills.all
    assert profile.quality.completeness_score >= 0.6


def test_resume_style_parsing_handles_links_and_role_location_split() -> None:
    sample_text = """
Siddharth Rajendran
siddharthr4925@gmail.com ❖ +91 9150897914 ❖ linkedin.com/in/siddharth20s ❖ github.com/siddharth20s ❖ Chennai, India

PROFESSIONAL SUMMARY
DevOps & Cloud Engineer with 2+ years of experience operating AWS and Azure infrastructure in production healthcare environments.

WORK EXPERIENCE
Kanini Software Solutions Apr 2024 - Present
DevOps / Cloud Engineer Chennai, India
• Built and maintained GitHub Actions and Azure DevOps CI/CD pipelines.
• Managed EKS clusters and incident response.

PROJECTS
CloudOps Command Center (Open Source) 2026 - Present
React · ASP.NET Core · PostgreSQL · Kubernetes · Terraform · GitHub Actions · ArgoCD github.com/siddharth20s/cloudops-
command-center
• Built a cloud operations platform.

Healthcare Cloud Infrastructure Automation Platform 2024 - 2025
Terraform · Azure · Bicep · Azure DevOps · PostgreSQL
• Built Terraform plan/apply gates and rollback workflows.

EDUCATION
B.E. in Electronics & Communication Engineering
Graduated 2023
""".strip()

    document_info = DocumentInfo(
        file_name="resume_sample.txt",
        file_type="txt",
        parsed_at_utc="2026-01-01T00:00:00+00:00",
    )

    profile = build_profile_from_text(sample_text, document_info)

    assert profile.candidate.headline == "DevOps & Cloud Engineer"
    assert profile.candidate.contact.location == "Chennai, India"
    assert any(link.network == "linkedin" for link in profile.candidate.contact.profile_links)
    assert any(link.network == "github" for link in profile.candidate.contact.profile_links)

    assert profile.experience
    assert profile.experience[0].company == "Kanini Software Solutions"
    assert profile.experience[0].title == "DevOps / Cloud Engineer"
    assert profile.experience[0].location == "Chennai, India"

    assert len(profile.projects) == 2
    assert any("cloudops-command-center" in link for link in profile.projects[0].links)
    assert profile.education
    assert profile.education[0].field_of_study == "Electronics & Communication Engineering"
    assert profile.education[0].end_date == "2023-01"
    assert profile.quality.completeness_score < 1.0


def test_skill_aliases_are_canonicalized() -> None:
    sample_text = """
Jane Doe
jane@example.com | +1 555 123 4567 | Chennai, India

SUMMARY
Platform engineer profile.

WORK EXPERIENCE
Cloud Team Jan 2024 - Present
Cloud Engineer Chennai, India
- Worked on Azure App Services and EntraID integration.

EDUCATION
B.E. in Computer Science

SKILLS
Azure Bicep · EntraID · REST APIs · SQL Server · MS SQL Server · Git Ops · GitHub Action
""".strip()

    document_info = DocumentInfo(
        file_name="skills_aliases.txt",
        file_type="txt",
        parsed_at_utc="2026-01-01T00:00:00+00:00",
    )

    profile = build_profile_from_text(sample_text, document_info)

    assert "bicep" in profile.skills.all
    assert "entra id" in profile.skills.all
    assert "rest api" in profile.skills.all
    assert "ms sql server" in profile.skills.all
    assert "gitops" in profile.skills.all
    assert "github actions" in profile.skills.all

    assert "entraid" not in profile.skills.all
    assert "azure bicep" not in profile.skills.all
    assert "sql server" not in profile.skills.all
