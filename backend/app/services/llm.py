"""LLM analysis of an extracted document.

Domain: research papers (PROJECT_SPEC.md §7 — pick one and commit), so
key_fields is {title, authors, methodology, key_findings, datasets}.

Provider boundary: everything below is provider-agnostic except `_complete()`,
which is the single function that talks to a model. Today it is a deterministic
stub so the pipeline runs with no API key; swapping in Claude Haiku or
gpt-4o-mini means implementing `_complete()` and nothing else. The defensive
JSON handling around it is real, not stubbed, so it is already exercised.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

CATEGORY = "research-paper"

KEY_FIELD_NAMES = ("title", "authors", "methodology", "key_findings", "datasets")

PROMPT = """You are analyzing a research paper. Reply with JSON only, no prose \
and no markdown fences.

Schema:
{{"summary": "2-3 sentence plain-English summary",
  "category": "research-paper",
  "key_fields": {{"title": string|null, "authors": [string], \
"methodology": string|null, "key_findings": [string], "datasets": [string]}}}}

Paper text:
{text}
"""

STRICTER_SUFFIX = (
    "\n\nYour previous reply was not valid JSON. Reply with the raw JSON object "
    "only. Do not include explanation, apology, or markdown fences."
)


class LLMError(Exception):
    """The model call failed in a way that may succeed on a retry.

    Timeouts and rate limits are the motivating cases. M2 wires this to Celery's
    retry; M1 records it as a failure.
    """


@dataclass
class Analysis:
    summary: str
    category: str | None
    key_fields: dict = field(default_factory=dict)
    model: str = ""
    token_count: int | None = None


def analyze_document(text: str) -> Analysis:
    """Summarize + classify + extract key fields from document text."""
    truncated = _truncate(text)
    prompt = PROMPT.format(text=truncated)

    raw = _complete(prompt)
    parsed = _parse(raw)

    if parsed is None:
        # Spec §7: on malformed JSON, retry once with a stricter prompt...
        logger.warning("LLM returned unparseable JSON; retrying with stricter prompt")
        raw = _complete(prompt + STRICTER_SUFFIX)
        parsed = _parse(raw)

    if parsed is None:
        # ...then store what you can rather than crashing the task.
        logger.error("LLM output still unparseable; storing degraded result")
        return Analysis(
            summary=raw.strip()[:2000] or "(model returned no usable output)",
            category=None,
            key_fields={},
            model=settings.llm_model,
            token_count=_estimate_tokens(truncated),
        )

    return Analysis(
        summary=parsed["summary"],
        category=parsed["category"],
        key_fields=parsed["key_fields"],
        model=settings.llm_model,
        token_count=_estimate_tokens(truncated),
    )


def _truncate(text: str) -> str:
    limit = settings.llm_max_input_chars
    if len(text) <= limit:
        return text
    logger.info("truncating document text from %d to %d chars", len(text), limit)
    return text[:limit]


def _estimate_tokens(text: str) -> int:
    """Rough char/4 heuristic. A real provider reports exact usage instead."""
    return len(text) // 4


def _parse(raw: str) -> dict | None:
    """Parse a model reply into the expected shape, or None if unusable.

    Tolerates the two things models do most often even when told not to:
    wrapping JSON in markdown fences, and padding it with prose.
    """
    candidate = raw.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        return None

    key_fields = data.get("key_fields")
    if not isinstance(key_fields, dict):
        key_fields = {}

    category = data.get("category")
    return {
        "summary": data["summary"],
        "category": category if isinstance(category, str) else None,
        "key_fields": {name: key_fields.get(name) for name in KEY_FIELD_NAMES},
    }


def _complete(prompt: str) -> str:
    """The provider boundary — the only function that would call a model API.

    Replace the stub branch with a real client call (and raise LLMError on
    timeout/rate-limit) to go live. Everything above stays as is.
    """
    _maybe_inject_fault()

    if settings.llm_provider == "stub":
        return _stub_complete(prompt)
    raise LLMError(f"llm_provider {settings.llm_provider!r} is not implemented yet")


def _maybe_inject_fault() -> None:
    """Simulate a provider timeout, for exercising the retry path.

    Off unless llm_fault_mode says otherwise, so this is inert in normal runs.
    It earns its place rather than being test scaffolding: §11 M4 requires
    mocking an LLM timeout, and faking it here — at the real provider boundary,
    raising the real exception type — tests the actual retry wiring instead of
    a mock of it.
    """
    mode = settings.llm_fault_mode
    if mode == "off":
        return

    if mode == "always":
        raise LLMError("injected fault: simulated provider timeout")

    if mode == "first_n":
        # Which attempt this is comes from the running Celery task; retries is
        # 0 on the first execution. Outside a task there is nothing to count,
        # so treat it as attempt 0.
        from celery import current_task

        retries = 0
        if current_task is not None and current_task.request is not None:
            retries = current_task.request.retries or 0
        if retries < settings.llm_fault_attempts:
            raise LLMError(
                f"injected fault: simulated provider timeout on attempt {retries + 1}"
            )
        return

    raise LLMError(f"unknown llm_fault_mode {mode!r}")


def _stub_complete(prompt: str) -> str:
    """Deterministic fake reply derived from the real extracted text.

    Derived, not hardcoded, so a broken extraction still shows up as broken
    output instead of being masked by a canned response. The stub is labelled in
    two places — the "[stub]" summary prefix and the model column ("stub-v0") —
    so stub rows can never be mistaken for real analysis in the database.
    """
    text = prompt.split("Paper text:", 1)[-1].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    title = lines[0][:200] if lines else None
    authors: list[str] = []
    if len(lines) > 1:
        second = lines[1]
        # A byline is short, comma-separated, and has no digits; anything else
        # is body text and gets left alone.
        if len(second) < 200 and not any(ch.isdigit() for ch in second):
            authors = [a.strip() for a in second.split(",") if a.strip()][:10]

    collapsed = " ".join(text.split())
    summary = f"[stub] {collapsed[:240]}" + ("..." if len(collapsed) > 240 else "")

    return json.dumps(
        {
            "summary": summary,
            "category": CATEGORY,
            "key_fields": {
                "title": title,
                "authors": authors,
                "methodology": None,
                "key_findings": [],
                "datasets": [],
            },
        }
    )
