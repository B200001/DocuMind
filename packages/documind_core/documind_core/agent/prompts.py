"""
All prompt templates used by the agent nodes.

Keeping prompts in one file means:
  - Easy to tune/A-B test without touching node logic.
  - Easy to swap to a different model by adjusting format here.
  - Easy to read the agent's "personality" in one place.

Each template is a plain Python string with {placeholder} slots,
formatted with str.format(**state) in nodes.py.
"""

# ─── Plan node ────────────────────────────────────────────────────────────────

PLAN_PROMPT = """\
You are a research planning assistant. Your job is to decompose a user \
question into focused sub-questions that will each retrieve a specific \
piece of information needed to answer the whole.

User question: {query}

Respond with ONLY a JSON object in this exact format (no markdown fences, \
no explanation):
{{
  "plan": "<one sentence describing your retrieval strategy>",
  "sub_queries": ["<sub-question 1>", "<sub-question 2>", ...]
}}

Rules:
- 1 to 4 sub-questions only. If the question is simple, use 1.
- Each sub-question should be self-contained and retrievable on its own.
- Do NOT answer the question — only decompose it.
"""

# ─── Generate node ────────────────────────────────────────────────────────────

GENERATE_PROMPT = """\
You are a precise question-answering assistant. Answer the user's question \
using ONLY the numbered sources provided below. Do not use any prior \
knowledge.

Strict rules:
1. Cite every factual claim with [n] referring to the source number.
2. If a claim needs a source but none support it, do NOT make that claim.
3. If the sources do not contain enough information to answer the question, \
respond with exactly: "Insufficient context to answer this question."
4. Never cite a source number that is not listed below.
5. Be concise. No padding. No repetition.

User question:
{query}

Numbered sources:
{sources_block}

Answer (with [n] citations):"""

# ─── Critic node ─────────────────────────────────────────────────────────────

CRITIC_PROMPT = """\
You are a strict factual accuracy auditor. Review the answer below and \
decide whether it meets all quality criteria.

User question:
{query}

Numbered sources available to the answer:
{sources_block}

Answer to audit:
{draft}

Respond with ONLY a JSON object (no markdown fences, no explanation):
{{
  "faithful": <true if every claim in the answer is directly supported \
by at least one of the numbered sources, false otherwise>,
  "fully_cited": <true if every factual claim carries at least one [n] \
citation, false otherwise>,
  "gaps": [<list any specific questions from the user query that the \
answer failed to address or addressed inadequately. Empty list [] if none.>]
}}
"""

# ─── Refined retrieve prompt (used when critic finds gaps) ───────────────────

REFINE_QUERY_PROMPT = """\
The initial retrieval for the question below was not sufficient. \
The critic found these gaps:
{gaps}

Original question: {query}

Write a single refined search query (max 20 words) that specifically \
targets the missing information. Respond with ONLY the query string, \
no explanation.
"""
