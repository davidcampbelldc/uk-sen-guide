"""RAG synthesis: top-N chunks + query → natural-language answer with citations.

Supports two LLM providers, chosen at startup based on env vars:

  * **Anthropic Claude** — set `ANTHROPIC_API_KEY`.
    Default model: `claude-sonnet-4-6`. Override with `UK_SEN_ANTHROPIC_MODEL`.
  * **z.ai / GLM** (OpenAI-compatible) — set `Z_AI_API_KEY`.
    Default model: `glm-4.6`. Override with `UK_SEN_ZAI_MODEL`.
    Base URL override: `UK_SEN_ZAI_BASE_URL`.

If both env vars are set, Anthropic is preferred. If neither is set, the
synthesizer degrades gracefully and returns a fixed escalation message
pointing to IPSEA.

Features:
  * Per-answer "This is information, not legal advice" disclaimer
  * Low-confidence escalation: if top fused score below threshold, skip LLM
    and return a deterministic "contact IPSEA" message (saves cost, avoids
    hallucination on weak retrievals)
  * Token + cost tracking per call (costs shown in GBP)
  * Numbered citations [1], [2] tied to source chunks
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

log = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 800
CONFIDENCE_THRESHOLD = 0.30  # top fused score below → skip LLM, escalate

# ── Provider defaults ─────────────────────────────────────────────────────
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
ZAI_DEFAULT_MODEL = "glm-4.6"
ZAI_DEFAULT_BASE_URL = "https://api.z.ai/api/paas/v4/"

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

LLM_ERROR_MESSAGE = (
    "Synthesis failed: the language model call did not complete (see sources below — "
    "retrieval worked, only the summary step failed). You can review the top sources "
    "directly or retry. If this persists, check the server logs for provider errors "
    "(billing, rate limits, network)."
)

NO_API_KEY_MESSAGE = (
    "Answer synthesis is disabled — no LLM API key set. Set either ANTHROPIC_API_KEY "
    "(uses Claude Sonnet 4.6) or Z_AI_API_KEY (uses GLM-4.6 via z.ai's OpenAI-compatible "
    "endpoint) to enable cited natural-language answers. Raw retrieval results are still "
    "available via POST /search."
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


# Approximate cost per 1M tokens, converted to GBP at ~0.80 USD/GBP for display.
_COST_PER_M_GBP = {
    # Anthropic Claude Sonnet 4.6 ($3 input / $15 output, × 0.80)
    "claude-sonnet-4-6": {"input": 2.40, "output": 12.00},
    # Z.ai GLM-4.6 (~$0.60 / $2.20 per 1M tokens, × 0.80)
    "glm-4.6": {"input": 0.48, "output": 1.76},
    "glm-4.5": {"input": 0.48, "output": 1.76},
    "glm-4.5-flash": {"input": 0.09, "output": 0.22},
}


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
    provider: str = ""                    # "anthropic" | "z.ai" | ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_gbp: float = 0.0


class _Provider:
    """Small abstraction over one of Anthropic or z.ai (OpenAI-compatible)."""

    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model

    def chat(self, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        """Return (text, input_tokens, output_tokens)."""
        raise NotImplementedError


class _AnthropicProvider(_Provider):
    def __init__(self, api_key: str, model: str):
        super().__init__("anthropic", model)
        self._client = Anthropic(api_key=api_key)

    def chat(self, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()
        return text, resp.usage.input_tokens, resp.usage.output_tokens


class _ZaiProvider(_Provider):
    def __init__(self, api_key: str, model: str, base_url: str):
        super().__init__("z.ai", model)
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        input_tokens = resp.usage.prompt_tokens if resp.usage else 0
        output_tokens = resp.usage.completion_tokens if resp.usage else 0
        return text, input_tokens, output_tokens


def _select_provider() -> _Provider | None:
    """Anthropic preferred, then z.ai, else None."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        model = os.environ.get("UK_SEN_ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)
        log.info("synthesis provider=anthropic model=%s", model)
        return _AnthropicProvider(anthropic_key, model)

    zai_key = os.environ.get("Z_AI_API_KEY")
    if zai_key:
        model = os.environ.get("UK_SEN_ZAI_MODEL", ZAI_DEFAULT_MODEL)
        base_url = os.environ.get("UK_SEN_ZAI_BASE_URL", ZAI_DEFAULT_BASE_URL)
        log.info("synthesis provider=z.ai model=%s base_url=%s", model, base_url)
        return _ZaiProvider(zai_key, model, base_url)

    log.warning("No ANTHROPIC_API_KEY or Z_AI_API_KEY set — synthesis disabled")
    return None


class RagSynthesizer:
    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        provider: _Provider | None = None,
    ):
        self.provider = provider if provider is not None else _select_provider()
        self.max_tokens = max_tokens
        self.confidence_threshold = confidence_threshold

    # Backwards-compat hint for the API server (`.client is not None`)
    @property
    def client(self) -> Any:
        return self.provider

    def synthesize(self, query: str, retrieved_results: list[Any]) -> SynthesisResult:
        if not retrieved_results:
            return self._escalate(query, confidence="out_of_scope")

        top = retrieved_results[0]
        top_score = _top_fused_score(top)
        if top_score < self.confidence_threshold:
            return self._escalate(query, confidence="low")

        if self.provider is None:
            return SynthesisResult(
                query=query,
                answer=NO_API_KEY_MESSAGE,
                citations=[],
                confidence="out_of_scope",
                escalated=True,
            )

        citations = _build_citations(retrieved_results[:5])
        user_prompt = _format_user_prompt(query, citations)

        try:
            text, input_tokens, output_tokens = self.provider.chat(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=self.max_tokens,
            )
        except Exception as exc:
            log.error(
                "synthesis provider error — retrieval was fine, LLM call failed: "
                "provider=%s model=%s top_fused_score=%.3f top_source=%s error=%s",
                self.provider.name,
                self.provider.model,
                top_score,
                citations[0].source if citations else "",
                exc,
            )
            # Preserve the citations so the UI can still show what retrieval found.
            # Confidence state is 'llm_error' — distinct from 'low' (weak retrieval).
            return SynthesisResult(
                query=query,
                answer=LLM_ERROR_MESSAGE,
                citations=citations,
                confidence="llm_error",
                escalated=True,
                provider=self.provider.name,
                model=self.provider.model,
            )

        cost_gbp = _cost_gbp(self.provider.model, input_tokens, output_tokens)

        return SynthesisResult(
            query=query,
            answer=text,
            citations=citations,
            confidence="high" if top_score >= 0.55 else "medium",
            escalated=False,
            provider=self.provider.name,
            model=self.provider.model,
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


def _cost_gbp(model: str, input_tokens: int, output_tokens: int) -> float:
    rate = _COST_PER_M_GBP.get(model)
    if not rate:
        return 0.0
    return (input_tokens / 1_000_000) * rate["input"] + (output_tokens / 1_000_000) * rate["output"]
