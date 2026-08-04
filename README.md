# Resume Intake

Portable resume parsing service for PDF and DOCX files.

It produces a rich, normalized JSON output that can be plugged into:
- User profile autofill
- Candidate-job matching engines
- CRM / ATS enrichment workflows

## Features

- Parses `.pdf` and `.docx` resumes
- Extracts rich candidate details:
  - Name, headline, summary, contact details, social profiles
  - Experience, education, projects, certifications, languages
  - Categorized skills and inferred signals
- Returns structured metadata and quality indicators
- Exposes both:
  - Python API
  - REST API (FastAPI)
  - CLI for local pipelines and batch operations

## Quick Start

1. Create a virtual environment and install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

2. Parse one resume from CLI:

```powershell
resume-intake parse "D:\\path\\to\\resume.pdf" --pretty
```

3. Start API server:

```powershell
resume-intake-api
```

4. Parse via API:

```powershell
curl -X POST "http://127.0.0.1:8000/parse" -F "file=@D:/path/to/resume.pdf"
```

## Run With Docker

1. Build image:

```powershell
docker build -t resume-intake:latest .
```

2. Start container:

```powershell
docker run --rm -p 8000:8000 resume-intake:latest
```

3. Or run with compose:

```powershell
docker compose up --build
```

4. Hit endpoints:

```powershell
curl.exe http://127.0.0.1:8000/health
curl.exe http://127.0.0.1:8000/schema
curl.exe -X POST "http://127.0.0.1:8000/parse" -F "file=@D:/path/to/resume.pdf"
```

OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

## API Endpoints

- `GET /health`
- `GET /schema`
- `POST /parse` (multipart file upload)

## Output Contract

The output is a stable schema from `ResumeProfile` and is designed to be application-neutral.

Use `GET /schema` for JSON schema generation at runtime.

## Notes

- Native `.doc` (legacy Word format) is not included by default.
- Scanned PDFs without embedded text require OCR before parsing.
