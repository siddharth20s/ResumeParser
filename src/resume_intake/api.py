from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile

from resume_intake.pipeline import parse_resume_file
from resume_intake.schema import ResumeProfile

SUPPORTED_SUFFIXES = {".pdf", ".docx"}

app = FastAPI(
    title="Resume Intake API",
    description="Portable resume parsing API with rich structured output",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "resume-intake",
        "utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/schema")
def schema() -> dict[str, object]:
    return ResumeProfile.model_json_schema()


@app.post("/parse")
async def parse_resume_endpoint(file: UploadFile = File(...)) -> dict[str, object]:
    file_name = file.filename or ""
    suffix = Path(file_name).suffix.lower()

    if suffix not in SUPPORTED_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed}")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    temp_path: Path | None = None

    try:
        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(raw_bytes)

        profile = parse_resume_file(temp_path)
        return profile.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Parsing failed: {exc}") from exc
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def run() -> None:
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("resume_intake.api:app", host=host, port=port, reload=False)
