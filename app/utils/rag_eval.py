"""RAG retrieval & generation quality metrics.

Industry-standard evaluation for RAG correctness — NOT perplexity
(which measures token-level language model quality, not retrieval
or grounding fidelity).

Metrics implemented:
  - Retrieval recall@k / precision@k (when ground-truth chunks known)
  - Answer faithfulness (n-gram grounding ratio against evidence)
  - Answer relevance (token/bigram overlap with query)
  - Citation coverage (fraction of claims backed by cited evidence)
  - ROUGE-L F1 (longest common subsequence vs reference)
  - Token-level hallucination ratio (tokens not traceable to evidence)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalQualityMetrics:
    """Metrics for how well the retriever found the right evidence."""
    recall_at_k: float          # fraction of relevant docs retrieved
    precision_at_k: float       # fraction of retrieved docs that are relevant
    reciprocal_rank: float      # 1 / rank of first relevant doc
    k: int


@dataclass(frozen=True)
class GenerationQualityMetrics:
    """Metrics for how faithful / relevant the generated response is."""
    faithfulness: float         # fraction of answer n-grams grounded in evidence
    relevance: float            # answer-vs-query topical similarity
    citation_coverage: float    # fraction of answer sentences with citations
    hallucination_ratio: float  # fraction of answer tokens absent from evidence
    rouge_l_f1: float           # ROUGE-L F1 vs reference answer (if available)


# ---------------------------------------------------------------------------
# Retrieval quality
# ---------------------------------------------------------------------------

def compute_retrieval_quality(
    retrieved_ids: list[str],
    relevant_ids: set[str],
) -> RetrievalQualityMetrics:
    """Compute recall@k, precision@k, and MRR from known relevant set."""
    if not relevant_ids:
        return RetrievalQualityMetrics(
            recall_at_k=0.0, precision_at_k=0.0, reciprocal_rank=0.0, k=len(retrieved_ids),
        )

    k = len(retrieved_ids)
    hits = [rid for rid in retrieved_ids if rid in relevant_ids]
    recall = len(set(hits)) / len(relevant_ids) if relevant_ids else 0.0
    precision = len(hits) / k if k else 0.0

    rr = 0.0
    for idx, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            rr = 1.0 / idx
            break

    return RetrievalQualityMetrics(
        recall_at_k=round(recall, 4),
        precision_at_k=round(precision, 4),
        reciprocal_rank=round(rr, 4),
        k=k,
    )


# ---------------------------------------------------------------------------
# Generation quality
# ---------------------------------------------------------------------------

_TOKENIZE_RE = re.compile(r'[a-z0-9]+')
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')
_CITATION_RE = re.compile(r'\[[\w\-]+\]')


def _tokenize(text: str) -> list[str]:
    return _TOKENIZE_RE.findall(text.lower())


def _bigrams(tokens: list[str]) -> set[str]:
    return {f'{tokens[i]} {tokens[i+1]}' for i in range(len(tokens) - 1)} if len(tokens) >= 2 else set()


def _trigrams(tokens: list[str]) -> set[str]:
    return {f'{tokens[i]} {tokens[i+1]} {tokens[i+2]}' for i in range(len(tokens) - 2)} if len(tokens) >= 3 else set()


def compute_faithfulness(answer: str, evidence_texts: list[str]) -> float:
    """Fraction of answer bigrams+trigrams that appear in at least one evidence chunk.

    Higher = more grounded.  Industry threshold: ≥ 0.60 considered faithful.
    """
    answer_tokens = _tokenize(answer)
    if len(answer_tokens) < 3:
        return 1.0  # trivially grounded

    answer_ngrams = _bigrams(answer_tokens) | _trigrams(answer_tokens)
    if not answer_ngrams:
        return 1.0

    evidence_ngrams: set[str] = set()
    for ev in evidence_texts:
        ev_tokens = _tokenize(ev)
        evidence_ngrams |= _bigrams(ev_tokens) | _trigrams(ev_tokens)

    if not evidence_ngrams:
        return 0.0

    grounded = len(answer_ngrams & evidence_ngrams)
    return round(grounded / len(answer_ngrams), 4)


def compute_relevance(answer: str, query: str) -> float:
    """Token + bigram overlap between answer and original query.

    Measures whether the answer is topically on-target.
    """
    a_tokens = _tokenize(answer)
    q_tokens = _tokenize(query)
    if not a_tokens or not q_tokens:
        return 0.0

    a_set = set(a_tokens)
    q_set = set(q_tokens)
    token_overlap = len(a_set & q_set) / max(len(q_set), 1)

    a_bi = _bigrams(a_tokens)
    q_bi = _bigrams(q_tokens)
    bigram_overlap = len(a_bi & q_bi) / max(len(q_bi), 1) if q_bi else 0.0

    return round(0.6 * token_overlap + 0.4 * bigram_overlap, 4)


def compute_citation_coverage(answer: str) -> float:
    """Fraction of answer sentences that contain at least one [chunk_id] citation."""
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(answer) if s.strip()]
    if not sentences:
        return 1.0

    cited = sum(1 for s in sentences if _CITATION_RE.search(s))
    return round(cited / len(sentences), 4)


def compute_hallucination_ratio(answer: str, evidence_texts: list[str]) -> float:
    """Fraction of answer tokens (len > 3) NOT found in any evidence.

    Lower = better.  Industry threshold: ≤ 0.35 acceptable.
    """
    answer_tokens = [t for t in _tokenize(answer) if len(t) > 3]
    if not answer_tokens:
        return 0.0

    evidence_vocab: set[str] = set()
    for ev in evidence_texts:
        evidence_vocab.update(t for t in _tokenize(ev) if len(t) > 3)

    if not evidence_vocab:
        return 1.0

    unsupported = sum(1 for t in answer_tokens if t not in evidence_vocab)
    return round(unsupported / len(answer_tokens), 4)


def compute_rouge_l_f1(candidate: str, reference: str) -> float:
    """ROUGE-L F1 using longest common subsequence."""
    c_tokens = _tokenize(candidate)
    r_tokens = _tokenize(reference)
    if not c_tokens or not r_tokens:
        return 0.0

    lcs_len = _lcs_length(c_tokens, r_tokens)
    precision = lcs_len / len(c_tokens)
    recall = lcs_len / len(r_tokens)
    if precision + recall == 0:
        return 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return round(f1, 4)


def _lcs_length(a: list[str], b: list[str]) -> int:
    """O(n*m) LCS — acceptable for response-length texts (< 500 tokens)."""
    m, n = len(a), len(b)
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[n]


def compute_generation_quality(
    answer: str,
    query: str,
    evidence_texts: list[str],
    reference_answer: str | None = None,
) -> GenerationQualityMetrics:
    """Compute all generation quality metrics in one call."""
    return GenerationQualityMetrics(
        faithfulness=compute_faithfulness(answer, evidence_texts),
        relevance=compute_relevance(answer, query),
        citation_coverage=compute_citation_coverage(answer),
        hallucination_ratio=compute_hallucination_ratio(answer, evidence_texts),
        rouge_l_f1=compute_rouge_l_f1(answer, reference_answer) if reference_answer else 0.0,
    )
