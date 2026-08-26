"""llm_verifier.py — LLM-as-a-Verifier for Fosved Office v2

Lightweight verification module inspired by the llm-as-a-verifier framework.
Provides fine-grained scoring, best-of-N selection, self-verification,
and ranking — all callable via call_python() bridge from Metalogos.

Functions (whitelisted in llm_proxy.py CALL_PYTHON_ALLOWED):
  - select(problem, candidates, criteria) -> int          — best-of-N selection
  - score(problem, candidate, criteria)   -> float         — fine-grained confidence 0.0-1.0
  - verify(problem, answer)               -> dict          — self-verification with breakdown
  - rank(problem, candidates, criteria)   -> list[dict]    — ranked list of {index, score}

Design principles (from llm-as-a-verifier paper):
  1. Fine-grained scoring granularity (1-20 scale mapped to 0.0-1.0)
  2. Criteria-based evaluation (multiple dimensions)
  3. LLM acts as verifier using structured prompt with forced score extraction
  4. Cheap/fast models for verification (DeepSeek, Groq, ZAI)

Usage from Metalogos:
  call_python("llm_verifier", "verify", json_encode(["question", "answer"]))
  call_python("llm_verifier", "select", json_encode(["problem", ["c1","c2","c3"], "Correctness: Does it solve the problem?"]))
  call_python("llm_verifier", "score", json_encode(["problem", "candidate", "criteria"]))
  call_python("llm_verifier", "rank", json_encode(["problem", ["c1","c2"], "criteria"]))
"""

import os
import json
import re
import logging

log = logging.getLogger("llm_verifier")

# ──────────────────────────── PROVIDER CONFIG ────────────────────────────
# Uses the same providers as llm_proxy.py but selects cheap/fast models
# for verification (not generation). Verification is a judging task.

_VERIFIER_PROVIDERS = [
    {
        "name": "deepseek",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "env_key": "DEEPSEEK_API_KEY",
        "model": "deepseek-chat",
        "format": "openai",
    },
    {
        "name": "zai",
        "url": "https://api.z.ai/api/paas/v4/chat/completions",
        "env_key": "ZAI_API_KEY",
        "model": "glm-4-flash",
        "format": "openai",
    },
    {
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "env_key": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
        "format": "openai",
    },
    {
        "name": "cerebras",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "env_key": "CEREBRAS_API_KEY",
        "model": "gpt-oss-120b",
        "format": "openai",
    },
]


# ──────────────────────────── LLM CALL PRIMITIVE ────────────────────────────

def _call_verifier_llm(messages, max_tokens=256, temperature=0.1):
    """Call a verifier LLM with fallback chain. Returns reply string or None.
    Uses low temperature (0.1) for deterministic scoring."""
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    for prov in _VERIFIER_PROVIDERS:
        api_key = os.environ.get(prov["env_key"])
        if not api_key:
            continue

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": prov["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            req = Request(
                prov["url"],
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            reply = data["choices"][0]["message"]["content"]
            log.debug(f"Verifier OK: provider={prov['name']} model={prov['model']}")
            return reply
        except Exception as e:
            log.debug(f"Verifier fail: provider={prov['name']} err={e}")
            continue

    return None


# ──────────────────────────── SCORE EXTRACTION ────────────────────────────

# Map letter tokens A-T to 1-20 scale (like the reference implementation)
_SCORE_TOKEN_MAP = {chr(ord("A") + i): i + 1 for i in range(20)}


def _extract_score(raw_reply, fallback=0.5):
    """Extract numeric score from LLM reply.
    
    Looks for patterns:
    1. 'SCORE: X' or 'Оценка: X' (explicit marker)
    2. Standalone number 1-20 on the last line
    3. Letter A-T on the last line
    4. Fallback to 0.5 (neutral)
    """
    if not raw_reply:
        return fallback

    lines = raw_reply.strip().split("\n")
    last_line = lines[-1].strip()

    # Pattern 1: explicit SCORE: marker
    score_match = re.search(r"(?:SCORE|Оценка|Score|score|Балл|ОЦЕНКА)[:\s]+([0-9]+(?:\.[0-9]+)?)", raw_reply)
    if score_match:
        val = float(score_match.group(1))
        # Normalize 1-20 to 0.0-1.0
        if val <= 20:
            return val / 20.0
        # If already 0-1 or 0-100, normalize
        if val <= 1.0:
            return val
        if val <= 100:
            return val / 100.0
        return fallback

    # Pattern 2: standalone number on last line
    num_match = re.match(r"^([0-9]+)$", last_line)
    if num_match:
        val = int(num_match.group(1))
        if 1 <= val <= 20:
            return val / 20.0
        return fallback

    # Pattern 3: single letter A-T on last line
    if len(last_line) == 1 and last_line.upper() in _SCORE_TOKEN_MAP:
        return _SCORE_TOKEN_MAP[last_line.upper()] / 20.0

    # Pattern 4: JSON with score field
    try:
        parsed = json.loads(raw_reply.strip())
        if isinstance(parsed, dict) and "score" in parsed:
            val = float(parsed["score"])
            if val <= 20:
                return val / 20.0
            return min(val, 1.0)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return fallback


def _extract_reasoning(raw_reply):
    """Extract reasoning text (everything before the score marker)."""
    if not raw_reply:
        return ""
    # Remove the score line
    lines = raw_reply.strip().split("\n")
    reasoning_lines = []
    for line in lines:
        if re.match(r"^(?:SCORE|Оценка|Score|score|Балл|ОЦЕНКА)[:\s]", line):
            break
        # Skip standalone score on last line
        reasoning_lines.append(line)
    # Remove last line if it's just a number or letter
    if reasoning_lines:
        last = reasoning_lines[-1].strip()
        if re.match(r"^([0-9]+)$", last) or (len(last) == 1 and last.upper() in _SCORE_TOKEN_MAP):
            reasoning_lines.pop()
    return "\n".join(reasoning_lines).strip()


# ──────────────────────────── PROMPT TEMPLATES ────────────────────────────

_VERIFY_PROMPT = """You are a verification judge. Evaluate whether the answer correctly addresses the problem.

Problem: {problem}

Answer: {answer}

Evaluate on these criteria:
- Accuracy: Does the answer contain correct information?
- Relevance: Does the answer address what was asked?
- Completeness: Are all aspects of the question covered?
- Hallucination: Does the answer contain fabricated information?

Provide brief reasoning (2-3 sentences), then output:
SCORE: <number 1-20>

Rating: 1=completely wrong, 10=partially correct, 20=fully correct"""


_SCORE_PROMPT = """You are an expert evaluator. Score this candidate response against the criteria.

Problem: {problem}

Candidate: {candidate}

Evaluation Criteria:
{criteria}

Provide brief reasoning, then output:
SCORE: <number 1-20>

Rating: 1=incorrect, 10=borderline, 20=correct"""


_SELECT_PROMPT = """You are evaluating multiple candidate responses. For EACH candidate, score it against the criteria.

Problem: {problem}

{candidates_text}

Evaluation Criteria:
{criteria}

For each candidate, provide:
- Brief reasoning (1 sentence)
- SCORE: <number 1-20>

Rating: 1=incorrect, 10=borderline, 20=correct"""


def _format_candidates(candidates):
    """Format candidates list for the select/rank prompt."""
    parts = []
    for i, c in enumerate(candidates):
        # Truncate very long candidates to save tokens
        text = c if len(c) <= 1500 else c[:1500] + "...[truncated]"
        parts.append(f"Candidate {i + 1}:\n{text}")
    return "\n---\n".join(parts)


# ──────────────────────────── PUBLIC API ────────────────────────────

def verify(problem, answer):
    """Self-verification: check if an answer correctly addresses a problem.
    
    Args:
        problem: The original question/task (string)
        answer: The generated answer to verify (string)
    
    Returns:
        dict with keys: score (float 0-1), reasoning (string), confidence (str)
    
    Usage from mlog:
        let result = call_python("llm_verifier", "verify", json_encode([query, reply]))
        let score = json_get(parse_json(result), "score", 0.5)
    """
    if not problem or not answer:
        return {"score": 0.5, "reasoning": "Missing input", "confidence": "low"}

    prompt = _VERIFY_PROMPT.format(problem=problem[:2000], answer=answer[:3000])
    messages = [
        {"role": "system", "content": "You are a precise verification judge. Always end with SCORE: <1-20>."},
        {"role": "user", "content": prompt},
    ]

    raw = _call_verifier_llm(messages, max_tokens=300, temperature=0.1)
    score = _extract_score(raw, fallback=0.5)
    reasoning = _extract_reasoning(raw)

    # Confidence level based on score
    if score >= 0.75:
        confidence = "high"
    elif score >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"

    log.info(f"verify: score={score:.2f} confidence={confidence}")
    return {"score": round(score, 4), "reasoning": reasoning[:500], "confidence": confidence}


def score(problem, candidate, criteria="Correctness: Does the response solve the problem accurately?"):
    """Fine-grained scoring of a single candidate against criteria.
    
    Args:
        problem: The task/problem description (string)
        candidate: The candidate response to score (string)
        criteria: Evaluation criteria (string, optional)
    
    Returns:
        float: score from 0.0 to 1.0
    
    Usage from mlog:
        let s = call_python("llm_verifier", "score", json_encode([problem, candidate, criteria]))
    """
    if not problem or not candidate:
        return 0.5

    prompt = _SCORE_PROMPT.format(
        problem=problem[:2000],
        candidate=candidate[:3000],
        criteria=criteria[:1000],
    )
    messages = [
        {"role": "system", "content": "You are an expert evaluator. Always end with SCORE: <1-20>."},
        {"role": "user", "content": prompt},
    ]

    raw = _call_verifier_llm(messages, max_tokens=256, temperature=0.1)
    s = _extract_score(raw, fallback=0.5)
    log.info(f"score: {s:.2f}")
    return round(s, 4)


def select(problem, candidates, criteria="Correctness: Does the response solve the problem accurately?"):
    """Best-of-N selection: pick the best candidate from a list.
    
    Uses individual scoring (not pairwise) for efficiency.
    Scores each candidate, returns the index of the best one.
    
    Args:
        problem: The task/problem description (string)
        candidates: List of candidate responses (list of strings)
        criteria: Evaluation criteria (string, optional)
    
    Returns:
        int: index (0-based) of the best candidate
    
    Usage from mlog:
        let best = call_python("llm_verifier", "select", json_encode([problem, [c1, c2, c3], criteria]))
    """
    if not candidates or not isinstance(candidates, list) or len(candidates) == 0:
        return 0
    if len(candidates) == 1:
        return 0

    scores = []
    for i, c in enumerate(candidates):
        s = score(problem, c, criteria)
        scores.append((i, s))

    # Sort by score descending, return best index
    scores.sort(key=lambda x: x[1], reverse=True)
    best_idx = scores[0][0]
    best_score = scores[0][1]
    log.info(f"select: best_index={best_idx} best_score={best_score:.2f} from {len(candidates)} candidates")
    return best_idx


def rank(problem, candidates, criteria="Correctness: Does the response solve the problem accurately?"):
    """Rank all candidates by score, returning sorted list.
    
    Args:
        problem: The task/problem description (string)
        candidates: List of candidate responses (list of strings)
        criteria: Evaluation criteria (string, optional)
    
    Returns:
        list of dicts: [{"index": int, "score": float}, ...] sorted by score descending
    
    Usage from mlog:
        let ranked = call_python("llm_verifier", "rank", json_encode([problem, [c1, c2], criteria]))
    """
    if not candidates or not isinstance(candidates, list) or len(candidates) == 0:
        return []

    results = []
    for i, c in enumerate(candidates):
        s = score(problem, c, criteria)
        results.append({"index": i, "score": round(s, 4)})

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"rank: {len(results)} candidates, top={results[0] if results else 'none'}")
    return results
