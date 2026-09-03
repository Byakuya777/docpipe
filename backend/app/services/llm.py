"""LLM analysis of an extracted document.

Domain: research papers (PROJECT_SPEC.md §7 — pick one and commit), so
key_fields is {title, authors, methodology, key_findings, datasets}.

Provider boundary: everything here is provider-agnostic except `_complete()`,
which is the only function that talks to a model. `anthropic` calls Claude;
`stub` returns a deterministic fake so the pipeline still runs with no API key
and no network. The defensive JSON handling around the call is shared by both.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)

CATEGORY = "research-paper"

KEY_FIELD_NAMES = ("title", "authors", "methodology", "key_findings", "datasets")

SYSTEM_PROMPT = """You analyze research papers and reply with JSON only — no \
prose, no markdown fences.

Reply with exactly this shape:
{"summary": "2-3 sentence plain-English summary of what the paper does",
 "category": "research-paper",
 "key_fields": {"title": string|null,
                "authors": [string],
                "methodology": string|null,
                "key_findings": [string],
                "datasets": [string]}}

Rules:
- Use null for a field the text does not support, and [] for an empty list.
- Do not invent authors, datasets, or findings that are not in the text.
- The text may be truncated mid-sentence; summarize what is present.
- Ignore publisher boilerplate, licence stamps, and copyright headers when \
identifying the title."""

STRICTER_SUFFIX = (
    "\n\nYour previous reply was not valid JSON. Reply with the raw JSON object "
    "only. Do not include explanation, apology, or markdown fences."
)


class LLMError(Exception):
    """The model call failed in a way that may succeed on a retry.

    Timeouts, rate limits, and 5xx responses. Celery retries these with backoff.
    """


class LLMPermanentError(Exception):
    """The model call failed in a way retrying cannot fix.

    A bad API key, a revoked key, or a malformed request will fail identically
    on every attempt, so the task fails the document immediately instead of
    burning four attempts and ~15 seconds of backoff to learn nothing.
    """


@dataclass
class Completion:
    """One model reply, plus whatever usage the provider reported."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


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

    completion = _complete(SYSTEM_PROMPT, truncated)
    parsed = _parse(completion.text)

    if parsed is None:
        # Spec §7: on malformed JSON, retry once with a stricter prompt...
        logger.warning("LLM returned unparseable JSON; retrying with stricter prompt")
        completion = _complete(SYSTEM_PROMPT + STRICTER_SUFFIX, truncated)
        parsed = _parse(completion.text)

    tokens = _total_tokens(completion, truncated)

    if parsed is None:
        # ...then store what you can rather than crashing the task.
        logger.error("LLM output still unparseable; storing degraded result")
        return Analysis(
            summary=completion.text.strip()[:2000] or "(model returned no usable output)",
            category=None,
            key_fields={},
            model=settings.llm_model,
            token_count=tokens,
        )

    return Analysis(
        summary=parsed["summary"],
        category=parsed["category"],
        key_fields=parsed["key_fields"],
        model=settings.llm_model,
        token_count=tokens,
    )


def _truncate(text: str) -> str:
    limit = settings.llm_max_input_chars
    if len(text) <= limit:
        return text
    logger.info("truncating document text from %d to %d chars", len(text), limit)
    return text[:limit]


def _total_tokens(completion: Completion, text: str) -> int | None:
    """Real usage when the provider reports it, char/4 for the stub."""
    if completion.input_tokens is None and completion.output_tokens is None:
        return len(text) // 4
    return (completion.input_tokens or 0) + (completion.output_tokens or 0)


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


def _complete(system: str, document_text: str) -> Completion:
    """The provider boundary — the only function that talks to a model."""
    _maybe_inject_fault()

    if settings.llm_provider == "stub":
        return _stub_complete(document_text)
    if settings.llm_provider == "anthropic":
        return _anthropic_complete(system, document_text)
    raise LLMPermanentError(f"unknown llm_provider {settings.llm_provider!r}")


@lru_cache(maxsize=1)
def _client():
    """One client per worker process, built lazily.

    Celery preforks, so building this at import time would create a client in
    the parent and hand every child a copy of its connection pool.
    """
    import anthropic

    kwargs = {
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_sdk_max_retries,
    }
    if settings.anthropic_api_key:
        kwargs["api_key"] = settings.anthropic_api_key
    if settings.anthropic_workspace_id:
        # Identity-linked keys are rejected with a 400 without this header.
        kwargs["default_headers"] = {
            "anthropic-workspace-id": settings.anthropic_workspace_id
        }
    return anthropic.Anthropic(**kwargs)


def _anthropic_complete(system: str, document_text: str) -> Completion:
    import anthropic

    try:
        response = _client().messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_output_tokens,
            system=system,
            messages=[{"role": "user", "content": document_text}],
        )
    # Most specific first. The split below is the whole point: recoverable
    # failures become LLMError (Celery retries with backoff), everything else
    # becomes LLMPermanentError (fail the document now).
    except anthropic.AuthenticationError as exc:
        raise LLMPermanentError(f"authentication failed: {exc}") from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMPermanentError(f"permission denied: {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise LLMPermanentError(f"model or endpoint not found: {exc}") from exc
    except anthropic.BadRequestError as exc:
        raise LLMPermanentError(f"bad request: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"rate limited: {exc}") from exc
    except anthropic.APITimeoutError as exc:
        raise LLMError(f"request timed out after {settings.llm_timeout_seconds}s") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"could not reach the API: {exc}") from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            raise LLMError(f"server error {exc.status_code}: {exc}") from exc
        raise LLMPermanentError(f"api error {exc.status_code}: {exc}") from exc

    if response.stop_reason == "refusal":
        # Not retryable — the same text will be declined again.
        raise LLMPermanentError("the model declined to analyze this document")
    if response.stop_reason == "max_tokens":
        # The JSON is almost certainly cut off; the parser will catch it, but
        # say so plainly in the log rather than leaving a confusing parse error.
        logger.warning(
            "reply hit max_tokens (%d); JSON is likely truncated",
            settings.llm_max_output_tokens,
        )

    text = "".join(block.text for block in response.content if block.type == "text")

    return Completion(
        text=text,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def _stub_complete(document_text: str) -> Completion:
    """Deterministic fake reply derived from the real extracted text.

    Derived, not hardcoded, so a broken extraction still shows up as broken
    output instead of being masked by a canned response.
    """
    lines = [line.strip() for line in document_text.splitlines() if line.strip()]

    title = lines[0][:200] if lines else None
    authors: list[str] = []
    if len(lines) > 1:
        second = lines[1]
        # A byline is short, comma-separated, and has no digits; anything else
        # is body text and gets left alone.
        if len(second) < 200 and not any(ch.isdigit() for ch in second):
            authors = [a.strip() for a in second.split(",") if a.strip()][:10]

    collapsed = " ".join(document_text.split())
    summary = f"[stub] {collapsed[:240]}" + ("..." if len(collapsed) > 240 else "")

    return Completion(
        text=json.dumps(
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
    )


def _maybe_inject_fault() -> None:
    """Simulate a provider timeout, for exercising the retry path.

    Off unless llm_fault_mode says otherwise. §11 M4 requires mocking an LLM
    timeout, and faking it here — at the real provider boundary, raising the
    real exception type — tests the actual retry wiring instead of a mock of it.
    """
    mode = settings.llm_fault_mode
    if mode == "off":
        return

    if mode == "always":
        raise LLMError("injected fault: simulated provider timeout")

    if mode == "first_n":
        # Which attempt this is comes from the running Celery task; retries is
        # 0 on the first execution. Outside a task there is nothing to count.
        from celery import current_task

        retries = 0
        if current_task is not None and current_task.request is not None:
            retries = current_task.request.retries or 0
        if retries < settings.llm_fault_attempts:
            raise LLMError(
                f"injected fault: simulated provider timeout on attempt {retries + 1}"
            )
        return

    raise LLMPermanentError(f"unknown llm_fault_mode {mode!r}")
