"""RAG synthesis: top-N chunks + query → natural-language answer with citations.

Uses Anthropic Claude (Sonnet 4.6) to synthesize a clear, confidently-cited
answer from retrieved chunks.

Features:
  * Per-answer "This is information, not legal advice" disclaimer
  * Low-confidence escalation: if top fused score below threshold, skip LLM
    and return a deterministic "contact IPSEA" message (saves cost, avoids
    hallucination on weak retrievals)
  * Token + cost tracking per call
  * Numbered citations [1], [2] tied to source chunks
  * Graceful degradation when ANTHROPIC_API_KEY is missing

Note on prompt caching: the system prompt is ~300 tokens, below Sonnet 4.6's
2,048-token cacheable prefix minimum — caching wouldn't activate. Skipped.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 800
CONFIDENCE_THRESHOLD = 0.30  # top fused score below → skip LLM, escalate

DISCLAIMER = (
    "This is general information based on public UK SEND guidance — not legal advice. "
    "For complex or urgent cases, contact IPSEA on 0800 018 4016, your local SENDIASS, "
    "or the SEND Tribunal directly."
)

ESCALATION_FALLBACK = (
    "I couldn't find guidance in my corpus that directly addresses this question. "
    "For questions outside the material I have access to — or urgent cases — "
    "please contact IPSEA on 0800 018 4016, your local SENDIASS, or consult a "
    "solicitor specialising in education law."
)

NO_API_KEY_MESSAGE = (
    "Answer synthesis is disabled (no ANTHROPIC_API_KEY set). "
    "Raw retrieval results are available via POST /search — or set ANTHROPIC_API_KEY "
    "to enable cited natural-language answers."
)

SYSTEM_PROMPT = (
    "You are a research assistant helping parents in the UK understand Special "
    "Educational Needs (SEN/SEND) guidance. You receive a parent's question and "
    "numbered source chunks drawn from UK statutory guidance (SEND Code of Practice), "
    "government pages, Local Authority Local Offers, and parent-advocacy charities "
    "(IPSEA, Contact).\n\n"
    "Your job:\n"
    "1. Write a clear, factual answer using ONLY the provided sources.\n"
    "2. Cite sources inline with [1], [2] etc. — every factual claim needs a citation.\n"
    "3. If the sources don't cover the question, say so plainly: \"The sources I have "
    "don't directly address X. Please contact IPSEA on 0800 018 4016 for specialist advice.\"\n"
    "4. Keep the answer under 250 words. Parents are often stressed; be warm, specific, "
    "actionable.\n"
    "5. Never invent legal duties, deadlines, or case outcomes beyond what the sources state.\n"
    "6. Never claim to be giving legal advice."
)


# Approximate cost per 1M tokens at list price (Sonnet 4.6).
# Converted to GBP at ~0.80 USD/GBP for user-facing display.
_SONNET_46_USD_PER_M = {"input": 3.00, "output": 15.00}
_USD_TO_GBP = 0.80


@dataclass
class Citation:
    number: int
    chunk_id: str
    doc_id: str | None
    source: str
    section_ref: str | None
    url: str | None
    excerpt: str


@dataclass
class SynthesisResult:
    query: str
    answer: str
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "high"              # "high" | "medium" | "low" | "out_of_scope"
    escalated: bool = False
    disclaimer: str = DISCLAIMER
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_gbp: float = 0.0


class RagSynthesizer:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        api_key: str | None = None,
    ):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.client: Anthropic | None = Anthropic(api_key=key) if key else None
        if self.client is None:
            log.warning("ANTHROPIC_API_KEY not set — synthesis will fall back to escalation message")
        self.model = model
        self.max_tokens = max_tokens
        self.confidence_threshold = confidence_threshold

    def synthesize(self, query: str, retrieved_results: list[Any]) -> SynthesisResult:
        """Take the top-N SearchResult-like objects and produce a cited answer."""
        if not retrieved_results:
            return self._escalate(query, confidence="out_of_scope")

        # Confidence gate — avoid LLM cost + hallucination on weak retrievals
        top = retrieved_results[0]
        top_score = _top_fused_score(top)
        if top_score < self.confidence_threshold:
            return self._escalate(query, confidence="low")

        # Graceful degradation when no API key
        if self.client is None:
            return SynthesisResult(
                query=query,
                answer=NO_API_KEY_MESSAGE,
                citations=[],
                confidence="out_of_scope",
                escalated=True,
            )

        # Build citations + user prompt
        citations = _build_citations(retrieved_results[:5])
        user_prompt = _format_user_prompt(query, citations)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:
            log.error("Claude API error: %s", exc)
            return self._escalate(query, confidence="low")

        answer_text = _extract_text(response)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost_gbp = _cost_gbp(input_tokens, output_tokens)

        return SynthesisResult(
            query=query,
            answer=answer_text,
            citations=citations,
            confidence="high" if top_score >= 0.55 else "medium",
            escalated=False,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_gbp=cost_gbp,
        )

    @staticmethod
    def _escalate(query: str, *, confidence: str) -> SynthesisResult:
        return SynthesisResult(
            query=query,
            answer=ESCALATION_FALLBACK,
            citations=[],
            confidence=confidence,
            escalated=True,
        )


# ── Helpers ────────────────────────────────────────────────────────────────


def _top_fused_score(result: Any) -> float:
    scores = getattr(result, "scores", {}) or {}
    return float(scores.get("fused", scores.get("semantic", 0.0)))


def _build_citations(results: list[Any]) -> list[Citation]:
    out: list[Citation] = []
    for i, r in enumerate(results, 1):
        source_ref = getattr(r, "source_ref", {}) or {}
        out.append(
            Citation(
                number=i,
                chunk_id=getattr(r, "chunk_id", ""),
                doc_id=getattr(r, "doc_id", None),
                source=source_ref.get("source", "") or "",
                section_ref=getattr(r, "section_ref", None),
                url=source_ref.get("url") or None,
                excerpt=(getattr(r, "text", "") or "")[:300],
            )
        )
    return out


def _format_user_prompt(query: str, citations: list[Citation]) -> str:
    sources: list[str] = []
    for c in citations:
        header = c.source
        if c.section_ref:
            header += f" §{c.section_ref}"
        sources.append(f"[{c.number}] Source: {header}\n{c.excerpt}")
    return f"Parent's question: {query}\n\nSources:\n\n" + "\n\n".join(sources)


def _extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def _cost_gbp(input_tokens: int, output_tokens: int) -> float:
    input_usd = (input_tokens / 1_000_000) * _SONNET_46_USD_PER_M["input"]
    output_usd = (output_tokens / 1_000_000) * _SONNET_46_USD_PER_M["output"]
    return (input_usd + output_usd) * _USD_TO_GBP
