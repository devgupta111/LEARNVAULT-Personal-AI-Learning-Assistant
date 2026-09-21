"""
services/grader_service.py

Day 6 — Hallucination & Citation Grader (Agent 3).

Responsibilities:
  - Evaluates a generated RAG answer for grounding and citation accuracy.
  - Checks whether all claims in the answer are supported by the ALREADY-RETRIEVED
    parent context chunks. Does NOT perform new retrieval.
  - Returns a structured GraderOutput: { grounded, confidence, critique }.
  - Uses dedicated GRADER_API_KEY / GRADER_MODEL from config, with RAG_API_KEY fallback.
  - Safe failure: if LLM call fails or output is invalid, returns grounded=False
    (treating grader failure as a grading failure → triggers one regeneration).

What the grader does NOT do:
  - Perform Qdrant retrieval.
  - Call CRAG.
  - Use web search or outside knowledge.
  - Generate a new answer.
  - Generate quiz questions.
  - Modify the database or Qdrant.

Failure path (defined in brain.md, enforced in chat.py):
  Generate answer
    → Grade
    → PASS: return answer
    → FAIL: regenerate ONCE with SAME context → grade again
            → PASS: return regenerated answer
            → FAIL: return existing Day-4 refusal

There is EXACTLY ONE regeneration attempt. This service is ONLY the grading step.

API keys are NEVER logged or exposed.
"""

import json
import logging
import re
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.schemas.chat_schemas import GraderOutput

logger = logging.getLogger(__name__)

# Grader system prompt — instructs the LLM to ONLY evaluate, not generate
GRADER_SYSTEM_PROMPT = """You are a strict Hallucination & Citation Grader for a RAG (Retrieval-Augmented Generation) system.

Your ONLY job is to evaluate whether a generated answer is properly grounded in the supplied source context.

You must output ONLY valid JSON matching this exact structure:
{
  "grounded": true | false,
  "confidence": 0.0 to 1.0,
  "critique": "..."
}

EVALUATION CRITERIA — mark grounded=false if ANY of these are violated:
1. Every factual claim in the answer must be directly supported by the provided context.
2. Citations such as [Source 1], [Source 2] must reference actual sources that support the associated claim.
3. The answer must not introduce facts, figures, or statements that are absent from the context.
4. The answer must not cite a source that does not support its associated claim.
5. The answer must not invent source IDs, page numbers, or quotes.

CONFIDENCE:
- Set confidence to a value between 0.0 and 1.0 reflecting how certain you are that grounded=true is correct.
- Use 0.9–1.0 for clearly grounded answers.
- Use 0.5–0.9 for partially grounded or uncertain.
- Use 0.0–0.5 for answers you believe contain unsupported claims.

CRITIQUE:
- If grounded=true: set critique to "" (empty string).
- If grounded=false: briefly describe the specific unsupported claim(s) or incorrect citation(s).

CRITICAL RULES:
- Do NOT suggest a new answer.
- Do NOT retrieve new information.
- Do NOT use knowledge outside the provided context.
- Do NOT add markdown or preamble outside the JSON object.
- Output ONLY the JSON object."""


def _get_grader_client() -> Tuple[object, str]:
    """
    Obtain the Groq client and model name for grading.

    Uses GRADER_API_KEY if configured; otherwise falls back to RAG_API_KEY.
    Uses GRADER_MODEL (default: openai/gpt-oss-120b).

    Raises:
        RuntimeError: If neither GRADER_API_KEY nor RAG_API_KEY is configured.
            Set GRADER_API_KEY=<your-groq-api-key> in your .env file.
    """
    api_key = settings.GRADER_API_KEY or settings.RAG_API_KEY
    if not api_key:
        raise RuntimeError(
            "Neither GRADER_API_KEY nor RAG_API_KEY is configured. "
            "Set GRADER_API_KEY=<your-groq-api-key> in your .env file."
        )

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except ImportError as exc:
        raise RuntimeError(
            "The 'groq' package is required. Install it with: pip install groq"
        ) from exc

    model = settings.GRADER_MODEL or "openai/gpt-oss-120b"
    logger.debug("Grader: using model=%s with GRADER_API_KEY", model)
    return client, model


def _format_context_for_grader(parent_results: List[Dict]) -> str:
    """
    Format retrieved parent context chunks for the grader prompt.

    Uses the same source numbering as the original RAG generation so the
    grader can verify [Source N] references in the answer.
    """
    blocks = []
    for i, ctx in enumerate(parent_results, start=1):
        page_start = ctx.get("page_start", "?")
        page_end = ctx.get("page_end", "?")
        if page_start == page_end:
            page_label = f"Page {page_start}"
        else:
            page_label = f"Page {page_start}-{page_end}"
        text = ctx.get("parent_text") or ctx.get("text") or ""
        # Truncate very long texts to keep the grader prompt within limits
        blocks.append(f"[Source {i} | {page_label}]\n{text[:3000]}")
    return "\n\n".join(blocks)


def grade_answer(
    question: str,
    answer: str,
    parent_results: List[Dict],
    citations: Optional[List[Dict]] = None,
) -> GraderOutput:
    """
    Grade a generated RAG answer for grounding and citation accuracy.

    The grader evaluates whether the answer's claims are supported by
    the ALREADY-RETRIEVED parent context. It does NOT perform new retrieval.

    Args:
        question:       The original user question.
        answer:         The generated answer to evaluate.
        parent_results: The retrieved parent context chunks used to generate the answer.
                        Must be the SAME context that was used for generation.
        citations:      Optional list of citation dicts (source_id, page_start, etc.)
                        extracted from parent_results. Used as additional grader context.

    Returns:
        GraderOutput with grounded (bool), confidence (float), and critique (str).

    Failure behaviour:
        On LLM failure, JSON parse failure, or Pydantic validation failure,
        returns GraderOutput(grounded=False, confidence=0.0, critique="Grader error")
        so the pipeline treats it as a grading failure and regenerates once.

    Note: This function is NEVER called for direct_chat or quiz responses.
    It is called ONLY after grounded RAG generation.
    """
    if not parent_results:
        logger.warning("Grader: No parent results provided. Treating as graded failure.")
        return GraderOutput(
            grounded=False,
            confidence=0.0,
            critique="No retrieved context was provided for grading.",
        )

    context_block = _format_context_for_grader(parent_results)

    # Build citation summary for the grader if available
    citation_summary = ""
    if citations:
        citation_lines = []
        for c in citations:
            src = c.get("source_id", "?")
            page_s = c.get("page_start", "?")
            page_e = c.get("page_end", "?")
            pid = c.get("parent_chunk_id", "?")[:12] if c.get("parent_chunk_id") else "?"
            citation_lines.append(
                f"  {src}: page {page_s}-{page_e}, chunk_id={pid}..."
            )
        citation_summary = "\nCITATIONS USED IN ANSWER:\n" + "\n".join(citation_lines)

    user_message = (
        f"STUDENT QUESTION:\n{question}\n\n"
        f"GENERATED ANSWER:\n{answer}\n\n"
        f"RETRIEVED CONTEXT USED FOR GENERATION:\n{context_block}"
        f"{citation_summary}\n\n"
        f"Evaluate whether the answer is fully grounded in the provided context. "
        f"Output ONLY valid JSON."
    )

    messages = [
        {"role": "system", "content": GRADER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        client, model = _get_grader_client()
        logger.info(
            "Grader: evaluating answer (len=%d) with model=%s",
            len(answer),
            model,
        )

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,   # Deterministic evaluation
            "max_tokens": 512,
            "stream": False,
        }
        # Groq rejects response_format=json_object for openai/ models
        if not model.startswith("openai/"):
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)
        raw_content = response.choices[0].message.content or "{}"

        # Parse JSON — try strict parse first, then regex extraction fallback
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            match = re.search(r"\{[^{}]*\}", raw_content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
            else:
                logger.warning(
                    "Grader: Could not parse JSON from response. Raw: %s",
                    raw_content[:200],
                )
                return GraderOutput(
                    grounded=False,
                    confidence=0.0,
                    critique="Grader output was not valid JSON.",
                )

        grounded = bool(parsed.get("grounded", False))
        confidence = float(parsed.get("confidence", 0.0))
        critique = str(parsed.get("critique", ""))

        result = GraderOutput(
            grounded=grounded,
            confidence=confidence,
            critique=critique,
        )

        logger.info(
            "Grader result: grounded=%s, confidence=%.2f, critique='%s'",
            result.grounded,
            result.confidence,
            result.critique[:100] if result.critique else "",
        )
        return result

    except Exception as exc:
        logger.warning(
            "Grader LLM call failed: %s. Treating as grading failure (safe fallback).",
            exc,
        )
        # Return graded=False so the pipeline triggers exactly one regeneration attempt.
        # This is the safe fallback: do not allow an unverified answer through.
        return GraderOutput(
            grounded=False,
            confidence=0.0,
            critique=f"Grader service error: {type(exc).__name__}",
        )
