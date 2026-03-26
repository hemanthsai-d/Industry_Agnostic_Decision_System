from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any, Protocol

import httpx

from app.models.schemas import EvidenceChunk, ResolutionProb
from app.models.intent_taxonomy import INTENT_BY_ID, get_category
from app.utils.pii_redaction import redact_pii

logger = logging.getLogger(__name__)

_CHANNEL_STYLE: dict[str, dict[str, str]] = {
    'twitter': {
        'max_length': '280 characters',
        'tone_hint': 'concise, conversational, empathetic',
        'format': 'Single short paragraph. No bullet points. Use contractions.',
    },
    'chat': {
        'max_length': '600 characters',
        'tone_hint': 'friendly, direct, action-oriented',
        'format': 'Short paragraphs. One clear next-step call-to-action.',
    },
    'email': {
        'max_length': '1500 characters',
        'tone_hint': 'professional, thorough, structured',
        'format': 'Greeting, context paragraph, numbered steps, closing.',
    },
    'phone': {
        'max_length': '800 characters',
        'tone_hint': 'warm, patient, clear',
        'format': 'Simple sentences. Avoid jargon. Summarise at end.',
    },
}
_DEFAULT_CHANNEL_STYLE = _CHANNEL_STYLE['chat']


@dataclass
class GenerationResult:
    text: str | None
    ok: bool
    reason_code: str | None = None
    used_fallback: bool = False
    backend: str = 'template'


@dataclass(frozen=True)
class StyleExample:
    source: str
    tone: str
    channel: str
    customer_text: str
    agent_text: str
    tags: tuple[str, ...] = ()


class TextGenerationBackend(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...


class OllamaTextGenerationBackend:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self._base_url = base_url.rstrip('/')
        self._model = model.strip()
        self._timeout_seconds = max(0.5, float(timeout_seconds))
        self._temperature = max(0.0, float(temperature))
        self._max_tokens = max(32, int(max_tokens))

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            'model': self._model,
            'stream': False,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'options': {
                'temperature': self._temperature,
                'num_predict': self._max_tokens,
            },
        }
        response = httpx.post(
            f'{self._base_url}/api/chat',
            json=payload,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        message = body.get('message')
        if not isinstance(message, dict):
            raise RuntimeError('Ollama response missing message object.')
        content = message.get('content')
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError('Ollama response missing message.content text.')
        return content.strip()


class GenerationService:
    def __init__(
        self,
        *,
        backend: str = 'template',
        model: str = 'qwen2.5:7b-instruct',
        ollama_base_url: str = 'http://localhost:11434',
        timeout_seconds: float = 8.0,
        temperature: float = 0.2,
        max_tokens: int = 320,
        max_history_turns: int = 8,
        similarity_threshold: float = 0.82,
        fail_open: bool = True,
        style_examples_path: str = 'artifacts/datasets/style_examples.jsonl',
        max_style_examples_per_prompt: int = 2,
        backend_client: TextGenerationBackend | None = None,
    ) -> None:
        self._backend_name = backend.strip().lower() or 'template'
        self._max_history_turns = max(1, int(max_history_turns))
        self._similarity_threshold = max(0.5, min(0.99, float(similarity_threshold)))
        self._fail_open = bool(fail_open)
        self._model = model.strip() or 'qwen2.5:7b-instruct'
        self._max_style_examples_per_prompt = max(0, int(max_style_examples_per_prompt))

        self._backend_client: TextGenerationBackend | None = None
        if backend_client is not None:
            self._backend_client = backend_client
            self._backend_name = 'custom'
        elif self._backend_name == 'ollama':
            self._backend_client = OllamaTextGenerationBackend(
                base_url=ollama_base_url,
                model=self._model,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            self._backend_name = 'template'
            self._backend_client = None

        self._style_examples = self._load_style_examples(style_examples_path)

    def build_grounded_response(
        self,
        issue_text: str,
        route_probs: list[ResolutionProb],
        evidence_pack: list[EvidenceChunk],
        context: dict[str, Any] | None = None,
    ) -> GenerationResult:
        ctx = context or {}
        if not evidence_pack:
            return GenerationResult(
                text=None,
                ok=False,
                reason_code='generation_no_evidence',
                backend=self._backend_name,
            )

        prior_assistant_messages = self._extract_prior_assistant_messages(ctx)
        generated = ''

        if self._backend_client is not None:
            system_prompt, user_prompt = self._build_prompts(
                issue_text=issue_text,
                route_probs=route_probs,
                evidence_pack=evidence_pack,
                context=ctx,
            )
            generated = self._generate_with_retry(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                prior_assistant_messages=prior_assistant_messages,
                evidence_pack=evidence_pack,
            )

        if generated:
            ensured = self._ensure_citations(generated, evidence_pack)
            return GenerationResult(
                text=ensured,
                ok=True,
                backend=self._backend_name,
            )

        if not self._fail_open:
            return GenerationResult(
                text=None,
                ok=False,
                reason_code='generation_backend_unavailable',
                backend=self._backend_name,
            )

        fallback = self._build_fallback_response(
            issue_text=issue_text,
            route_probs=route_probs,
            evidence_pack=evidence_pack,
            context=ctx,
        )
        return GenerationResult(
            text=fallback,
            ok=True,
            reason_code='generation_fallback_template',
            used_fallback=True,
            backend='template',
        )

    def _generate_with_retry(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prior_assistant_messages: list[str],
        evidence_pack: list[EvidenceChunk],
    ) -> str:
        if self._backend_client is None:
            return ''

        try:
            candidate = self._sanitize_generated_text(
                self._backend_client.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            )
        except Exception:
            logger.exception('Generative backend request failed.')
            return ''

        if self._passes_generation_checks(candidate, prior_assistant_messages, evidence_pack):
            return candidate

        retry_prompt = (
            user_prompt
            + '\n\nREWRITE REQUIREMENT: Regenerate with clearly different wording than previous assistant replies. '
            'Do not quote evidence text verbatim beyond short fragments. Keep the same facts and keep citations.'
        )
        try:
            retry_candidate = self._sanitize_generated_text(
                self._backend_client.generate(
                    system_prompt=system_prompt,
                    user_prompt=retry_prompt,
                )
            )
        except Exception:
            logger.exception('Generative backend retry failed.')
            return ''

        if self._passes_generation_checks(retry_candidate, prior_assistant_messages, evidence_pack):
            return retry_candidate
        return ''

    def _passes_generation_checks(
        self,
        candidate: str,
        prior_assistant_messages: list[str],
        evidence_pack: list[EvidenceChunk],
    ) -> bool:
        if not candidate or len(candidate) < 24:
            return False
        if self._is_too_similar_to_prior(candidate, prior_assistant_messages):
            return False
        if self._is_too_similar_to_evidence(candidate, evidence_pack):
            return False
        return True

    def _build_prompts(
        self,
        *,
        issue_text: str,
        route_probs: list[ResolutionProb],
        evidence_pack: list[EvidenceChunk],
        context: dict[str, Any],
    ) -> tuple[str, str]:
        top_route = route_probs[0].label if route_probs else 'general_support_triage'
        evidence_lines = [
            f"- [{item.chunk_id}] {self._summarize_evidence_text(item.text)}"
            for item in evidence_pack[:4]
        ]
        history_lines = self._extract_history_lines(context)
        prior_assistant = self._extract_prior_assistant_messages(context)
        style_directive = self._build_style_directive(context=context, issue_text=issue_text)
        style_examples = self._sample_style_examples(context=context, issue_text=issue_text)

        redaction = redact_pii(issue_text)
        safe_issue = redaction.text

        channel = self._safe_str(context.get('channel')).lower()
        channel_style = _CHANNEL_STYLE.get(channel, _DEFAULT_CHANNEL_STYLE)

        category = get_category(top_route) or 'GENERAL'

        profile = {
            'customer_name': self._safe_str(context.get('customer_name')),
            'account_tier': self._safe_str(context.get('account_tier')),
            'locale': self._safe_str(context.get('locale')),
            'preferred_tone': self._safe_str(context.get('preferred_tone')),
            'channel': self._safe_str(context.get('channel')),
        }
        profile_parts = [f'{k}={v}' for k, v in profile.items() if v]
        profile_text = ', '.join(profile_parts) if profile_parts else 'not provided'

        style_examples_block = [
            '- (none loaded; rely on direct personalization rules)'
        ]
        if style_examples:
            style_examples_block = [
                f"- [{example.source}|{example.tone}] customer='{self._trim_text(example.customer_text, 120)}' "
                f"agent='{self._trim_text(example.agent_text, 160)}'"
                for example in style_examples
            ]

        system_prompt = (
            'You are a senior customer support specialist. '
            'Respond like a skilled human agent with empathy and precision.\n'
            'Rules:\n'
            '1) Use evidence for facts; do not invent policy details.\n'
            '2) Do NOT copy prior assistant wording verbatim.\n'
            '3) Keep language natural, specific, and personalized.\n'
            '4) Include clear next steps and expected timeline when possible.\n'
            '5) Ask at most 2 clarification questions only if essential data is missing.\n'
            '6) Cite chunk ids like [chunk_id] for key factual statements.\n'
            '7) Do not sound templated or robotic.\n'
            f'8) Intent category: {category}. Tailor response to this domain.\n'
            f'9) Channel format: {channel_style["format"]}\n'
            f'10) Target max length: {channel_style["max_length"]}.\n'
            f'11) Tone: {channel_style["tone_hint"]}.'
        )

        user_prompt = '\n'.join(
            [
                f'Customer issue: {safe_issue}',
                f'Recommended route label: {top_route}',
                f'Intent category: {category}',
                f'Customer profile: {profile_text}',
                f'Style directive: {style_directive}',
                f'Channel: {channel or "chat"} (format: {channel_style["format"]})',
                'Evidence:',
                *evidence_lines,
                'Recent conversation:',
                *(history_lines if history_lines else ['- (no prior conversation provided)']),
                'Prior assistant answers (for anti-clone check):',
                *([f'- {self._trim_text(item, 220)}' for item in prior_assistant] if prior_assistant else ['- (none)']),
                'Reference style examples:',
                *style_examples_block,
                'Now produce a new response tailored for this customer.',
            ]
        )
        return system_prompt, user_prompt

    def _build_fallback_response(
        self,
        *,
        issue_text: str,
        route_probs: list[ResolutionProb],
        evidence_pack: list[EvidenceChunk],
        context: dict[str, Any],
    ) -> str:
        """Build a dynamic evidence-grounded response when the LLM backend is unavailable.

        Instead of canned sentences, this synthesises the response from the
        retrieved evidence and the customer's actual issue so every reply is
        unique to the request.
        """
        top_route = route_probs[0].label if route_probs else 'general_support_triage'
        route_human = top_route.replace('_', ' ')
        customer_name = self._safe_str(context.get('customer_name'))
        greeting = f'Hi {customer_name},' if customer_name else 'Hi,'

        # Dynamically pull the most relevant evidence text
        primary = evidence_pack[0]
        primary_summary = self._summarize_evidence_text(primary.text)

        lines = [greeting]

        # Acknowledge the customer's actual issue (not a generic greeting)
        trimmed_issue = self._trim_text(issue_text, 120)
        lines.append(
            f"I see you're reaching out about: \"{trimmed_issue}\". "
            f"Let me walk you through what applies here."
        )

        # Primary evidence-based guidance
        lines.append(
            f"Based on our {primary.source.replace('_', ' ')} documentation, "
            f"the recommended action is: {primary_summary} [{primary.chunk_id}]"
        )

        # Additional evidence chunks — each adds unique information
        for chunk in evidence_pack[1:3]:
            chunk_summary = self._summarize_evidence_text(chunk.text)
            lines.append(
                f"Additionally ({chunk.source.replace('_', ' ')}): "
                f"{chunk_summary} [{chunk.chunk_id}]"
            )

        # Route-specific next step
        lines.append(
            f"This falls under our {route_human} process. "
            "Would you like me to proceed with the next step, or do you have any questions?"
        )

        return '\n'.join(lines)

    def _build_style_directive(self, *, context: dict[str, Any], issue_text: str) -> str:
        preferred_tone = self._safe_str(context.get('preferred_tone')).lower()
        channel = self._safe_str(context.get('channel')).lower()
        account_tier = self._safe_str(context.get('account_tier')).lower()
        normalized_issue = self._normalize_text(issue_text)

        if preferred_tone in {'formal', 'professional', 'concise', 'empathetic', 'friendly'}:
            tone = preferred_tone
        elif any(term in normalized_issue for term in ('angry', 'frustrated', 'upset', 'cancel', 'fraud', 'stolen')):
            tone = 'empathetic'
        elif account_tier in {'enterprise', 'vip', 'premium'}:
            tone = 'professional'
        else:
            tone = 'friendly'

        channel_style = _CHANNEL_STYLE.get(channel, _DEFAULT_CHANNEL_STYLE)
        channel_hint = channel if channel else 'chat'
        return (
            f"Use a {tone} tone optimized for {channel_hint}. "
            f'{channel_style["format"]} '
            'Acknowledge the customer issue directly and provide concrete actions.'
        )

    def _sample_style_examples(self, *, context: dict[str, Any], issue_text: str) -> list[StyleExample]:
        if not self._style_examples or self._max_style_examples_per_prompt <= 0:
            return []

        preferred_tone = self._safe_str(context.get('preferred_tone')).lower()
        channel = self._safe_str(context.get('channel')).lower()
        issue_terms = self._token_set(issue_text)

        scored: list[tuple[float, StyleExample]] = []
        for example in self._style_examples:
            score = 0.0
            if preferred_tone and preferred_tone == example.tone:
                score += 2.0
            if channel and channel == example.channel:
                score += 1.5

            example_terms = self._token_set(example.customer_text)
            if issue_terms and example_terms:
                overlap = len(issue_terms & example_terms) / float(max(len(issue_terms), len(example_terms)))
                score += overlap

            scored.append((score, example))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = [example for score, example in scored if score > 0.0]
        if not top:
            top = [example for _, example in scored]
        return top[: self._max_style_examples_per_prompt]

    def _extract_history_lines(self, context: dict[str, Any]) -> list[str]:
        history = context.get('conversation_history')
        if not isinstance(history, list):
            return []

        lines: list[str] = []
        sliced = history[-self._max_history_turns :]
        for item in sliced:
            if isinstance(item, dict):
                role = self._safe_str(item.get('role') or item.get('speaker') or 'user').lower() or 'user'
                content = self._safe_str(item.get('content') or item.get('text') or item.get('message'))
            else:
                role = 'user'
                content = self._safe_str(item)
            if not content:
                continue
            lines.append(f"- {role}: {self._trim_text(content, 280)}")
        return lines

    def _extract_prior_assistant_messages(self, context: dict[str, Any]) -> list[str]:
        messages: list[str] = []
        history = context.get('conversation_history')
        if isinstance(history, list):
            for item in history[-self._max_history_turns :]:
                if not isinstance(item, dict):
                    continue
                role = self._safe_str(item.get('role') or item.get('speaker')).lower()
                if role != 'assistant':
                    continue
                content = self._safe_str(item.get('content') or item.get('text') or item.get('message'))
                if content:
                    messages.append(content)

        for key in ('previous_answer', 'last_agent_reply', 'previous_assistant_reply'):
            value = self._safe_str(context.get(key))
            if value:
                messages.append(value)

        dedup: list[str] = []
        seen = set()
        for item in messages:
            norm = self._normalize_text(item)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            dedup.append(item)
        return dedup

    def _is_too_similar_to_prior(self, candidate: str, prior_messages: list[str]) -> bool:
        if not prior_messages:
            return False
        candidate_tokens = self._token_set(candidate)
        if len(candidate_tokens) < 8:
            return False

        max_similarity = 0.0
        max_ngram_similarity = 0.0
        candidate_ngrams = self._ngram_set(candidate, n=4)

        for prior in prior_messages:
            prior_tokens = self._token_set(prior)
            if len(prior_tokens) >= 8:
                overlap = len(candidate_tokens & prior_tokens)
                similarity = overlap / float(max(len(candidate_tokens), len(prior_tokens)))
                max_similarity = max(max_similarity, similarity)

            prior_ngrams = self._ngram_set(prior, n=4)
            if candidate_ngrams and prior_ngrams:
                ngram_overlap = len(candidate_ngrams & prior_ngrams) / float(max(len(candidate_ngrams), len(prior_ngrams)))
                max_ngram_similarity = max(max_ngram_similarity, ngram_overlap)

        return (max_similarity >= self._similarity_threshold) or (max_ngram_similarity >= 0.55)

    def _is_too_similar_to_evidence(self, candidate: str, evidence_pack: list[EvidenceChunk]) -> bool:
        candidate_tokens = self._token_set(candidate)
        if len(candidate_tokens) < 10:
            return False

        for item in evidence_pack:
            evidence_tokens = self._token_set(item.text)
            if len(evidence_tokens) < 10:
                continue
            overlap = len(candidate_tokens & evidence_tokens)
            ratio = overlap / float(max(len(candidate_tokens), len(evidence_tokens)))
            if ratio >= 0.90:
                return True
        return False

    def _ensure_citations(self, text: str, evidence_pack: list[EvidenceChunk]) -> str:
        if self._has_evidence_citation(text, evidence_pack):
            return text
        citation_ids = ', '.join(f'[{item.chunk_id}]' for item in evidence_pack[:2])
        if not citation_ids:
            return text
        return f'{text}\n\nReferences: {citation_ids}'

    @staticmethod
    def _has_evidence_citation(text: str, evidence_pack: list[EvidenceChunk]) -> bool:
        if not text:
            return False
        for item in evidence_pack:
            if f'[{item.chunk_id}]' in text:
                return True
        return False

    @staticmethod
    def _sanitize_generated_text(value: str) -> str:
        text = value.strip()
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    @staticmethod
    def _summarize_evidence_text(value: str) -> str:
        text = ' '.join(value.split()).strip()
        if len(text) <= 170:
            return text
        return text[:167].rstrip() + '...'

    @staticmethod
    def _trim_text(value: str, limit: int) -> str:
        normalized = ' '.join(value.split()).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 3)].rstrip() + '...'

    @staticmethod
    def _safe_str(value: Any) -> str:
        if value is None:
            return ''
        return str(value).strip()

    @staticmethod
    def _normalize_text(value: str) -> str:
        return ' '.join(re.findall(r'[a-z0-9]+', value.lower()))

    @staticmethod
    def _token_set(value: str) -> set[str]:
        return {token for token in re.findall(r'[a-z0-9]+', value.lower()) if len(token) > 2}

    @staticmethod
    def _ngram_set(value: str, n: int = 4) -> set[str]:
        tokens = re.findall(r'[a-z0-9]+', value.lower())
        if len(tokens) < n:
            return set()
        return {' '.join(tokens[idx : idx + n]) for idx in range(0, len(tokens) - n + 1)}

    @staticmethod
    def _load_style_examples(path: str) -> list[StyleExample]:
        file_path = Path(path).expanduser()
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        if not file_path.exists():
            return []

        examples: list[StyleExample] = []
        try:
            with file_path.open('r', encoding='utf-8') as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue

                    customer_text = str(payload.get('customer_text') or '').strip()
                    agent_text = str(payload.get('agent_text') or '').strip()
                    if not customer_text or not agent_text:
                        continue

                    tags_raw = payload.get('tags')
                    tags = tuple(str(tag).strip() for tag in tags_raw) if isinstance(tags_raw, list) else ()
                    examples.append(
                        StyleExample(
                            source=str(payload.get('source') or 'external').strip() or 'external',
                            tone=str(payload.get('tone') or 'friendly').strip().lower() or 'friendly',
                            channel=str(payload.get('channel') or 'chat').strip().lower() or 'chat',
                            customer_text=customer_text,
                            agent_text=agent_text,
                            tags=tags,
                        )
                    )
        except Exception:
            logger.exception('Failed to load style examples from file.', extra={'path': str(file_path)})
            return []

        return examples
