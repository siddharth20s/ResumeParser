from __future__ import annotations

import argparse
import json
from pathlib import Path

from resume_intake.pipeline import parse_resume_file
from resume_intake.schema import ResumeProfile

SUPPORTED_SUFFIXES = {".pdf", ".docx"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-intake",
        description="Portable resume parsing CLI",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser("parse", help="Parse one file or a directory of resumes")
    parse_cmd.add_argument("input_path", help="Path to a PDF/DOCX file or folder")
    parse_cmd.add_argument("-o", "--output", help="Optional output JSON file")
    parse_cmd.add_argument("--pretty", action="store_true", help="Pretty print JSON output")

    subparsers.add_parser("schema", help="Print output JSON schema")

    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.command == "schema":
        payload = ResumeProfile.model_json_schema()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    input_path = Path(args.input_path)
    files = _collect_resume_files(input_path)

    results = [parse_resume_file(path).model_dump() for path in files]
    payload: dict[str, object] | object

    if len(results) == 1:
        payload = results[0]
    else:
        payload = {
            "count": len(results),
            "results": results,
        }

    json_output = json.dumps(payload, indent=2 if args.pretty else None, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(json_output, encoding="utf-8")
    else:
        print(json_output)

    return 0


def _collect_resume_files(input_path: Path) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")

    if input_path.is_file():
        suffix = input_path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported extension: {suffix}")
        return [input_path]

    files: list[Path] = []
    for suffix in SUPPORTED_SUFFIXES:
        files.extend(input_path.rglob(f"*{suffix}"))

    unique_files = sorted(set(files))
    if not unique_files:
        raise ValueError(f"No PDF or DOCX files found in directory: {input_path}")

    return unique_files


if __name__ == "__main__":
    raise SystemExit(main())
