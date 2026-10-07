"""
AI resume analysis & document extraction helpers.

- extract_text_from_file(file_path): pulls plain text out of a .pdf or
  .docx resume using PyPDF2 / python-docx.
- analyze_candidate_with_gemini(resume_path, job_title, required_certs):
  extracts the resume text internally, then sends it to Google's Gemini
  API (gemini-2.5-flash, via the `google-genai` SDK) with structured JSON
  output, and returns a normalized dict of match score / skills / summary
  / safety screening questions.

Both are defensive by design: extraction returns "" rather than raising on
an unreadable/unsupported file, and the AI call falls back to
DEFAULT_ANALYSIS on any error (missing API key, missing package, network
failure, malformed JSON, blocked response, timeout, etc). This module is
called from the application-submission request path, so it must never
raise and must never block indefinitely.
"""

import json
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover - dependency may not be installed yet
    PdfReader = None

try:
    import docx  # python-docx
except ImportError:  # pragma: no cover
    docx = None

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover
    genai = None
    genai_types = None


# ---------------------------------------------------------------------------
# 1. Text extraction
# ---------------------------------------------------------------------------

def extract_text_from_file(file_path):
    """
    Extract plain text from a .pdf or .docx resume file.

    Returns "" (not an exception) if the file is missing, unsupported, or
    unreadable, so callers can degrade gracefully instead of crashing the
    request that triggered this.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    try:
        if not path.exists():
            logger.warning("Resume file not found: %s", path)
            return ""
        if suffix == ".pdf":
            return _extract_pdf_text(path)
        if suffix == ".docx":
            return _extract_docx_text(path)
        if suffix == ".doc":
            logger.warning("Legacy .doc files are not supported for text extraction: %s", path)
            return ""
        logger.warning("Unsupported resume file type for extraction: %s", suffix)
        return ""
    except Exception:
        logger.exception("Failed to extract text from resume file: %s", path)
        return ""


def _extract_pdf_text(path):
    if PdfReader is None:
        raise RuntimeError("PyPDF2 is not installed. Run: pip install PyPDF2")
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages).strip()


def _extract_docx_text(path):
    if docx is None:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")
    document = docx.Document(str(path))
    paragraphs = [p.text for p in document.paragraphs]
    return "\n".join(paragraphs).strip()


# ---------------------------------------------------------------------------
# 2. AI analysis (Google Gemini via the `google-genai` SDK)
# ---------------------------------------------------------------------------

DEFAULT_ANALYSIS = {
    "match_score": 0,
    "skills_extracted": [],
    "summary": "AI analysis unavailable — please review this application manually.",
    "safety_questions": [
        "Describe a time you identified and reported a safety hazard on the job.",
        "Walk me through the correct lockout/tagout procedure before servicing a machine.",
        "What PPE would you wear for this role, and how do you check it's still safe to use?",
    ],
}

SYSTEM_PROMPT = (
    "You are an HR assistant for a factory hiring platform. You evaluate "
    "candidate resumes against a job title and its required certifications, "
    "for industrial/factory roles (machine operators, technicians, warehouse "
    "staff, etc.). Always respond with a single JSON object and nothing "
    "else, matching exactly this schema: "
    '{"match_score": integer 0-100, "skills_extracted": [string], '
    '"summary": string (max 2 sentences), "safety_questions": [string, string, string]}. '
    "match_score should reflect how well the candidate's experience and "
    "certifications meet the job's requirements — 0 if the resume is empty "
    "or irrelevant, 100 for a perfect match. skills_extracted should list "
    "concrete skills, tools, machinery, and certifications found in the "
    "resume. safety_questions must be exactly 3 practical, factory-floor "
    "safety or trade-competency screening questions an HR recruiter can ask "
    "during an in-person practical test, tailored to this specific role."
)


def analyze_candidate_with_gemini(resume_path, job_title, required_certs):
    """
    Extract text from `resume_path` and send it, with `job_title` and
    `required_certs`, to Gemini for structured analysis.

    Returns:
      {
        "match_score": int (0-100),
        "skills_extracted": [str, ...],
        "summary": str,
        "safety_questions": [str, str, str],
      }

    Falls back to DEFAULT_ANALYSIS on a missing/unreadable resume, a missing
    API key, a missing `google-genai` package, or any request/parsing
    failure. Never raises.
    """
    resume_text = extract_text_from_file(resume_path)
    if not resume_text.strip():
        return {**DEFAULT_ANALYSIS, "summary": "No readable resume text was found to analyze."}

    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY is not set; skipping AI resume analysis.")
        return DEFAULT_ANALYSIS
    if genai is None:
        logger.warning("The 'google-genai' package is not installed; skipping AI resume analysis.")
        return DEFAULT_ANALYSIS

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
            contents=_build_prompt(resume_text, job_title, required_certs),
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return _normalize(json.loads(response.text))
    except Exception:
        logger.exception("Gemini resume analysis failed; returning fallback result.")
        return DEFAULT_ANALYSIS


def _build_prompt(resume_text, job_title, required_certs):
    # Bound the resume length so we don't blow context size / cost on huge files.
    trimmed_resume = resume_text[:8000]
    certs = (required_certs or "").strip() or "None specified."
    return (
        f"JOB TITLE: {job_title}\n"
        f"REQUIRED CERTIFICATIONS: {certs}\n\n"
        f"CANDIDATE RESUME:\n{trimmed_resume}\n\n"
        "Analyze the resume against this job and respond with the JSON object described."
    )


def _normalize(data):
    """Coerce/validate Gemini's JSON into the expected shape, filling gaps with defaults."""
    if not isinstance(data, dict):
        return DEFAULT_ANALYSIS

    try:
        score = int(round(float(data.get("match_score", 0))))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))

    skills = data.get("skills_extracted")
    skills = skills if isinstance(skills, list) else []
    skills = [str(s).strip() for s in skills if str(s).strip()][:25]

    summary = str(data.get("summary") or DEFAULT_ANALYSIS["summary"]).strip()

    questions = data.get("safety_questions")
    questions = questions if isinstance(questions, list) else []
    questions = [str(q).strip() for q in questions if str(q).strip()][:3]
    defaults = DEFAULT_ANALYSIS["safety_questions"]
    while len(questions) < 3:
        questions.append(defaults[len(questions) % len(defaults)])

    return {
        "match_score": score,
        "skills_extracted": skills,
        "summary": summary,
        "safety_questions": questions,
    }