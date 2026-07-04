"""
Pure scoring functions for the three RAGAS-style metrics computed by
run_eval.py. Kept separate from the LLM-calling code in llm_judge.py so
the scoring MATH can be verified with hand-crafted inputs, independent of
whether Ollama is actually reachable.

METRICS
--------
faithfulness:
    Of the atomic factual claims in the generated answer, what fraction
    are actually supported by the retrieved context? Measures
    hallucination — a low score means the model said things the context
    doesn't back up.

answer_relevance:
    Does the answer actually address the question that was asked? We use
    RAGAS's actual method here: ask the LLM to generate several
    hypothetical questions that the answer would be a good response to,
    embed those alongside the original question, and average their
    cosine similarity to the original. A generic or evasive answer tends
    to produce generated questions that drift from the original.

context_precision:
    Of the retrieved chunks (in rank order), what fraction are actually
    relevant to answering the question, weighted so that irrelevant
    chunks ranked EARLY are penalized more than irrelevant chunks ranked
    late? This is the standard "average precision" formulation RAGAS uses.
"""

from __future__ import annotations

import math


def compute_faithfulness_score(claims: list[dict]) -> float:
    """
    Parameters
    ----------
    claims:
        A list of ``{"claim": str, "supported": bool}`` dicts, one per
        atomic factual claim extracted from the answer.

    Returns
    -------
    float
        supported_count / total_claims. Returns 1.0 if the answer made
        no factual claims at all (e.g. "Insufficient context to answer
        this question.") — an answer that claims nothing can't be
        unfaithful to the context.
    """
    if not claims:
        return 1.0
    supported = sum(1 for c in claims if c.get("supported"))
    return supported / len(claims)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity between two equal-length vectors."""
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_answer_relevance(
    original_embedding: list[float],
    generated_question_embeddings: list[list[float]],
) -> float:
    """
    Average cosine similarity between the original question's embedding
    and each of the LLM-generated hypothetical questions' embeddings.

    Parameters
    ----------
    original_embedding:
        Embedding vector of the real question that was asked.
    generated_question_embeddings:
        Embedding vectors of N hypothetical questions the LLM judged the
        answer to be a good response to.

    Returns
    -------
    float
        Mean cosine similarity. Returns 0.0 if no generated questions
        were provided (can't score relevance with nothing to compare against).
    """
    if not generated_question_embeddings:
        return 0.0
    similarities = [cosine_similarity(original_embedding, g) for g in generated_question_embeddings]
    return sum(similarities) / len(similarities)


def compute_context_precision(relevance_flags: list[bool]) -> float:
    """
    Parameters
    ----------
    relevance_flags:
        One bool per retrieved chunk, IN RANK ORDER (first = highest
        ranked), True if that chunk is actually relevant to the question.

    Returns
    -------
    float
        Average of precision@k computed at every rank k where the k-th
        chunk is relevant (the standard "Average Precision" formulation:
        irrelevant chunks ranked early hurt more than irrelevant chunks
        ranked late). Returns 0.0 if no chunk is relevant at all.

    Example
    -------
        [True, False, True, False]
        -> precision@1 = 1/1 = 1.0   (rank 1 is relevant)
        -> precision@3 = 2/3         (rank 3 is relevant; 2 of top-3 are relevant)
        -> average of those two = 0.833...
    """
    if not relevance_flags or not any(relevance_flags):
        return 0.0

    precisions_at_relevant_ranks: list[float] = []
    relevant_so_far = 0

    for k, is_relevant in enumerate(relevance_flags, start=1):
        if is_relevant:
            relevant_so_far += 1
            precisions_at_relevant_ranks.append(relevant_so_far / k)

    return sum(precisions_at_relevant_ranks) / len(precisions_at_relevant_ranks)
