"""
select_clips.py
Sends a transcript to Groq's free hosted API (Llama 3.3 70B) and asks it to
pick the best short-form clips, returning timestamps + ready-to-post
titles/descriptions/hashtags as structured JSON. Free tier, no local compute -
just needs a Groq API key and an internet connection.

ONE-TIME SETUP:
    1. Get a free API key at https://console.groq.com/keys
    2. Add it to .env as GROQ_API_KEY=gsk_...

Usage:
    python select_clips.py transcripts/myvideo.json --max-clips 8 \
        --min-duration 30 --max-duration 45

Output:
    clips/myvideo_plan.json  -> list of clip plans:
        {
          "start": 102.5,
          "end": 142.0,
          "title": "...",
          "description": "...",
          "reason": "..."
        }
"""

import os
import re
import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import load_dotenv

import token_budget
from run_control import check_cancelled, interruptible_sleep

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"  # free tier on Groq, far stronger than any local 7-14B model

# Each model on Groq's free tier has its own independent daily token budget.
# When the preferred model's budget runs out mid-day, fall through to the
# next model here rather than stopping entirely. Ordered roughly by expected
# quality; all support JSON mode and have large enough context windows for
# our chunking (verified against Groq's /models endpoint).
MODEL_FALLBACK_CHAIN = [
    MODEL,
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
]

# Reasoning-capable models can bleed their chain-of-thought into the JSON
# response unless explicitly told not to, which breaks response_format's
# strict JSON validation. "hidden" drops the reasoning entirely so content
# stays clean JSON - but reasoning tokens still count against the completion
# budget even when hidden, so a low/no reasoning_effort matters too, or the
# model can burn its whole output budget on hidden reasoning and truncate
# the actual JSON before it's complete. See https://console.groq.com/docs/reasoning
REASONING_FORMAT_OVERRIDES = {
    "openai/gpt-oss-120b": {"reasoning_format": "hidden", "reasoning_effort": "low"},
    "openai/gpt-oss-20b": {"reasoning_format": "hidden", "reasoning_effort": "low"},
    "qwen/qwen3.6-27b": {"reasoning_format": "hidden", "reasoning_effort": "none"},
}
# Generous ceiling so a multi-clip JSON response (plus any hidden reasoning
# tokens on models above) has enough room to finish instead of truncating
# mid-object, which itself produces invalid JSON.
MAX_COMPLETION_TOKENS = 4096

DEFAULT_MIN_DURATION = 30
DEFAULT_MAX_DURATION = 45
# min/max duration are a soft target for the model to aim for, not a hard
# filter - self-containment, hook quality, and the no-forced-padding rule
# already do the real quality enforcement, so a clip a bit outside the target
# window no longer gets thrown out for that alone. The one duration that IS
# a hard cutoff is YouTube's own Shorts eligibility limit - go over it and a
# video simply isn't a Short anymore, no matter how good the clip is.
SHORTS_MAX_DURATION = 180
SNAP_TOLERANCE = 1.5  # how far a timestamp may drift from a real segment edge and still snap to it

# Groq's free tier caps tokens-per-minute per request, and both the limit AND
# the real token count for the same content vary by model:
#   llama-3.3-70b-versatile: 12,000 TPM   openai/gpt-oss-120b: 8,000 TPM
#   qwen/qwen3.6-27b:         8,000 TPM   llama-3.1-8b-instant: 6,000 TPM (tightest)
# Size chunks for the tightest model in the chain, not just the primary one.
# The char/4 estimate also runs well short of real tokenization on dense,
# conversational transcripts - observed real "Requested" sizes were ~3x this
# estimate across all three fallback models on identical input (2,991
# estimated -> 8,499/10,042/8,524 actual). This constant is picked so that
# even at that ~3x real-world multiplier, a chunk stays safely under 6,000.
CHARS_PER_TOKEN = 4  # rough heuristic for English text
MAX_INPUT_TOKENS_PER_CHUNK = 1000
CHUNK_COOLDOWN_SECONDS = 65  # let the tokens-per-minute budget fully reset between chunks

# Rough overhead added on top of raw transcript tokens, used only to estimate
# whether a video fits in what's left of Groq's free-tier *daily* token budget
# before spending any calls on it (see token_budget.py).
SYSTEM_PROMPT_OVERHEAD_TOKENS = 700  # system prompt + JSON response, per chunk call
RERANK_OVERHEAD_TOKENS = 1500  # the extra rerank pass over all candidates, if it runs


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def chunk_segments(segments: list[dict], max_tokens: int = MAX_INPUT_TOKENS_PER_CHUNK) -> list[list[dict]]:
    """Split segments into groups that each stay under a rough per-request token
    budget, so one long transcript doesn't blow past Groq's tokens-per-minute limit."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_tokens = 0
    for seg in segments:
        seg_tokens = estimate_tokens(seg["text"]) + 8  # + a few tokens for timestamp formatting
        if current and current_tokens + seg_tokens > max_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(seg)
        current_tokens += seg_tokens
    if current:
        chunks.append(current)
    return chunks


HOOK_PATTERNS = """Every strong Shorts hook uses at least one of these mechanics in its
opening line (the first ~3 seconds of the clip, before any cut happens):
1. OPEN LOOP - state a question or promise ("here's the mistake nobody tells you
   about X") and only resolve it later in the clip. The viewer stays to get the payoff.
2. CONTRARIAN / PATTERN INTERRUPT - contradict a common belief or expectation
   immediately ("everyone thinks X, but that's backwards").
3. SPECIFIC STAKES OR NUMBERS - concrete, surprising specifics beat vague claims
   ("this one habit cost me $40k" beats "this habit is bad for you").
4. MID-ACTION DROP - start on a sentence that's already mid-story/mid-argument so
   it feels like the viewer just walked in on something interesting, not a lecture.
5. EMOTIONAL/RELATABLE CONFLICT - a moment of disagreement, frustration, surprise,
   or vulnerability that makes the viewer feel something in the first line."""


def build_performance_hint() -> str | None:
    """A short summary of which hook mechanics have actually retained viewers
    best on this channel so far (real YouTube Analytics retention, joined
    against our local hook_mechanic log), so future selection runs lean
    toward what's already working instead of guessing blind every time.
    Best-effort: returns None if there isn't enough upload history with
    real stats yet, or the YouTube Analytics API isn't authorized - the
    prompt just omits the section rather than failing the whole run over it."""
    try:
        from youtube_analytics import hook_mechanic_performance
        rows = hook_mechanic_performance()
    except Exception:
        return None

    ranked = sorted(rows, key=lambda r: r["avg_view_percentage"], reverse=True)
    if len(ranked) < 2:
        return None  # not enough distinct mechanics with real data yet to say anything meaningful

    lines = "\n".join(
        f"  - {r['hook_mechanic']}: {r['avg_view_percentage']}% avg retention (n={r['clip_count']})"
        for r in ranked
    )
    best, worst = ranked[0], ranked[-1]
    return f"""

PERFORMANCE DATA FROM THIS CHANNEL'S PAST UPLOADS (real YouTube retention, not a guess):
{lines}

'{best['hook_mechanic']}' is retaining viewers best so far and '{worst['hook_mechanic']}' worst.
When two candidate moments are otherwise similar in quality, prefer the mechanic with the
stronger track record above - but never force a weak moment into a high-performing mechanic
just to match the pattern; a clip must still genuinely earn its hook_mechanic label."""


def build_system_prompt(
    min_duration: float,
    max_duration: float,
    performance_hint: str | None = None,
) -> str:
    prompt = f"""You are a short-form video producer who has studied thousands of
viral YouTube Shorts / TikToks and knows exactly why some clips stop the scroll
and most don't. Your job is to mine a long-form transcript for the moments that
would actually perform, not just moments that are merely on-topic.

You will be given a transcript as a JSON array of {{start, end, text}} segments
(times in seconds, already split at natural sentence/pause boundaries).

{HOOK_PATTERNS}

Rules for picking clips:
- Each clip must be a SELF-CONTAINED moment that makes sense without context
  from the rest of the video, AND its opening line must hit one of the hook
  mechanics above. If the first line is throat-clearing or needs prior context
  to land, the clip is not strong enough - look for a different moment or a
  later starting point that opens harder.
- Target clip duration is {min_duration:.0f}-{max_duration:.0f} seconds, as a
  guide, not a hard rule - a genuinely self-contained, well-cut moment that
  runs a bit shorter or longer is still worth returning. The one real limit is
  {SHORTS_MAX_DURATION:.0f} seconds - beyond that it stops qualifying as a
  YouTube Short at all, so never propose a clip longer than that.
- CLEAN CUTS ONLY: "start" must exactly equal the "start" of one of the given
  segments, and "end" must exactly equal the "end" of one of the given segments.
  Never invent a timestamp in the middle of a segment - that chops a word or
  sentence in half and ruins the cut.
- Do not let clips overlap.
- End on a complete, quotable sentence/thought - never a trailing dependent
  clause - ideally a punchline, payoff, or a line strong enough to be the title.
- Skip filler, rambling, or moments whose only hook is "this is interesting" -
  vague interest is not a hook mechanic.
- Reject weak openings even if the middle of the moment is good; a great payoff
  with a flat hook still won't stop the scroll. Only return clips you are
  genuinely confident would make someone stop scrolling in the first 3 seconds.
  If the transcript doesn't support the requested number of clips at that bar,
  return fewer rather than padding with mediocre ones.
- Reject moments that lean on unexplained jargon, acronyms, or insider
  terminology a general viewer wouldn't already know (e.g. technical terms used
  without definition, org-specific shorthand). A clip can be about a technical
  subject, but it must be intelligible to someone with no prior background -
  if understanding the point requires already knowing what the jargon means,
  it is not self-contained, no matter how clean the cut is.

For each clip, write:
- "hook_mechanic": which of the 5 mechanics above the opening line uses (one of:
  "open_loop", "contrarian", "stakes_or_numbers", "mid_action", "emotional_conflict")
- "title": <=60 characters, written the same way the hook mechanic works (a
  contrarian clip gets a contrarian title, an open-loop clip gets a title that
  itself opens a loop) - never a flat/descriptive summary of the topic
- "description": 1-2 sentences, include 2-4 relevant hashtags (always include #Shorts)
- "reason": one short sentence naming the specific hook mechanic and why it works
  in this exact moment (not a generic "this is engaging")

Respond with ONLY a JSON object of this exact shape, no markdown fences, no
preamble, no explanation before or after:
{{
  "clips": [
    {{
      "start": 102.5,
      "end": 142.0,
      "hook_mechanic": "contrarian",
      "title": "The mistake everyone makes with X",
      "description": "Why most people get this wrong, explained in 30 seconds. #Shorts #productivity",
      "reason": "Opens by contradicting the common assumption about X, then proves it in 2 sentences"
    }}
  ]
}}
"""
    if performance_hint:
        prompt += performance_hint
    return prompt


def build_rerank_system_prompt(
    max_clips: int,
    min_duration: float,
    max_duration: float,
    performance_hint: str | None = None,
) -> str:
    prompt = f"""You are curating the final lineup of YouTube Shorts from a pool of
candidate clips that were picked independently from different parts of the same
video (so some may cover similar ground or vary in strength - you're seeing the
full picture for the first time).

{HOOK_PATTERNS}

Choose the {max_clips} strongest candidates to actually publish:
- Prioritize the clearest hook mechanic, the most self-contained payoff, and
  genuine "stop scrolling" strength over the others. A candidate with a vague or
  missing hook_mechanic loses to one with a sharp, well-executed one, even if
  the topic is less interesting on paper.
- Prefer variety in BOTH topic and hook_mechanic - if several candidates lean on
  the same mechanic or cover the same idea, keep only the strongest and drop the
  rest, so the final lineup doesn't feel repetitive.
- Target clip duration is {min_duration:.0f}-{max_duration:.0f} seconds; use that
  as a tiebreaker when candidates are otherwise similar in quality.

Respond with ONLY a JSON object of this exact shape, no markdown fences, no
preamble, no explanation before or after:
{{"selected_ids": [0, 3, 5]}}
"""
    if performance_hint:
        prompt += performance_hint
    return prompt


def rerank_clips(
    candidates: list[dict],
    max_clips: int,
    model: str,
    min_duration: float,
    max_duration: float,
    performance_hint: str | None = None,
    cancel_event=None,
) -> list[dict]:
    """Give the model a second pass over every candidate clip from every chunk at
    once, so the final cut is picked by comparing across the whole video instead
    of just truncating whatever order the per-chunk calls happened to return."""
    if len(candidates) <= max_clips:
        return candidates
    check_cancelled(cancel_event)

    numbered = [
        {
            "id": i,
            "hook_mechanic": c.get("hook_mechanic", "unknown"),
            "title": c["title"],
            "description": c["description"],
            "reason": c["reason"],
            "duration": round(c["end"] - c["start"], 1),
        }
        for i, c in enumerate(candidates)
    ]
    system_prompt = build_rerank_system_prompt(max_clips, min_duration, max_duration, performance_hint)
    user_prompt = (
        f"Here are {len(candidates)} candidate clips. Choose the best {max_clips} "
        f"to publish.\n\nCANDIDATES:\n{json.dumps(numbered, ensure_ascii=False)}"
    )

    print(f"[select_clips] Reranking {len(candidates)} candidates down to the best {max_clips}...")
    interruptible_sleep(CHUNK_COOLDOWN_SECONDS, cancel_event)  # stay under the tokens-per-minute limit after the last chunk call
    raw_text = call_groq(user_prompt, system_prompt, model=model).strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        selected_ids = json.loads(raw_text)["selected_ids"]
        selected = [candidates[i] for i in selected_ids if isinstance(i, int) and 0 <= i < len(candidates)]
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
        print(f"[select_clips] Warning: could not parse rerank response ({e}); "
              f"keeping the first {max_clips} candidates instead.")
        return candidates[:max_clips]

    return selected[:max_clips] if selected else candidates[:max_clips]


def load_transcript(transcript_path: str) -> list[dict]:
    with open(transcript_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_user_prompt(segments: list[dict], max_clips: int) -> str:
    transcript_json = "\n".join(
        f"{s['start']:.2f}|{s['end']:.2f}|{s['text']}"
        for s in segments
    )
    return (
        f"Find up to {max_clips} clips for YouTube Shorts from this transcript.\n\n"
        f"TRANSCRIPT:\n{transcript_json}"
    )


def _parse_reset_seconds(header: str) -> float:
    """Parse Groq's x-ratelimit-reset-tokens header (e.g. '1m5s', '8.5s') into seconds."""
    total = sum(
        float(v) * (60 if u.lower() == "m" else 1)
        for v, u in re.findall(r"(\d+(?:\.\d+)?)([mMs])", header)
    )
    return total if total > 0 else 70.0  # safe fallback if header is missing or unparseable


class GroqGenerationError(RuntimeError):
    """Raised when a model produces output Groq itself rejects as invalid
    (e.g. malformed JSON) - a model-compatibility problem, not a budget one,
    but handled the same way: move on to the next model in the chain."""


def call_groq(prompt: str, system: str, model: str = MODEL) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
            "and add it to your .env file as GROQ_API_KEY=..."
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }
    if model in REASONING_FORMAT_OVERRIDES:
        payload.update(REASONING_FORMAT_OVERRIDES[model])
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "User-Agent": "python-urllib/3.14",
    }

    for attempt in range(3):
        req = urllib.request.Request(GROQ_URL, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            token_budget.record_usage(model, body.get("usage", {}).get("total_tokens", 0))
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", "ignore")
            if e.code == 429 and "tokens per day" in body_text:
                # A daily cap won't reset within a retry cooldown like a per-minute
                # limit would, so stop immediately instead of burning retries on it.
                # Groq's error reports its own authoritative "Used X" count - sync our
                # local tracker to that instead of just leaving it wherever our own
                # (possibly incomplete, e.g. after a stale process made untracked
                # calls) accounting left it.
                used_match = re.search(r"Used (\d+)", body_text)
                if used_match:
                    token_budget.set_usage(model, int(used_match.group(1)))
                raise token_budget.GroqBudgetExhausted(
                    f"'{model}' has hit Groq's free-tier daily token budget: {body_text}"
                )
            if e.code == 400 and "json_validate_failed" in body_text:
                # Some models don't reliably honor response_format=json_object
                # for a given prompt - that's a model-compatibility issue, not
                # something a retry on the same model is likely to fix.
                raise GroqGenerationError(
                    f"'{model}' failed to produce valid JSON output: {body_text}"
                )
            if e.code == 413 and "Request too large" in body_text:
                # The chunk is bigger than THIS model's tokens-per-minute limit
                # (these vary by model - a fallback model can have a much lower
                # cap than the primary one). Retrying the identical request
                # won't shrink it, so don't waste attempts on it - treat it the
                # same as a model-compatibility problem and let the caller try
                # a different model instead.
                raise GroqGenerationError(
                    f"'{model}' rejected the request as too large for its per-minute limit: {body_text}"
                )
            if e.code in (413, 429) and attempt < 2:
                wait = _parse_reset_seconds(e.headers.get("x-ratelimit-reset-tokens", "")) + 5
                print(f"[select_clips] Groq rate limit hit; waiting {wait:.0f}s then retrying "
                      f"(attempt {attempt + 1}/3)...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Groq API error {e.code}: {body_text}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not reach Groq API ({GROQ_URL}): {e}")


def snap_to_segment_bounds(start: float, end: float, segments: list[dict]) -> tuple[float, float]:
    """Pull (start, end) onto the nearest real segment edge so the cut lands on a
    clean sentence boundary instead of mid-word, even if the model's timestamps drift."""
    if not segments:
        return start, end

    nearest_start = min((s["start"] for s in segments), key=lambda v: abs(v - start))
    nearest_end = min((s["end"] for s in segments), key=lambda v: abs(v - end))

    if abs(nearest_start - start) <= SNAP_TOLERANCE:
        start = nearest_start
    if abs(nearest_end - end) <= SNAP_TOLERANCE:
        end = nearest_end

    return start, end


def parse_clips_json(raw_text: str) -> list[dict]:
    """Defensive JSON parsing shared by the automated selection path and the
    "paste a plan from an external model" path - tolerates markdown fences
    despite instructions not to use them, and a bare array instead of the
    requested {"clips": [...]} shape."""
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse as JSON: {e}\n\nRaw text:\n{raw_text}"
        )

    if isinstance(parsed, dict):
        return next((v for v in parsed.values() if isinstance(v, list)), [])
    return parsed


def validate_clips(clips: list[dict], segments: list[dict]) -> list[dict]:
    """Snap timestamps to real segment edges and filter to clips that are
    long enough to be useful and short enough to stay Shorts-eligible.
    Shared by the automated selection path and the "paste a plan from an
    external model" path, so both get the same real guarantees regardless
    of which model (or human) produced the raw clip list."""
    valid_clips: list[dict] = []
    oversized = 0

    for c in clips:
        try:
            start, end = float(c["start"]), float(c["end"])
            start, end = snap_to_segment_bounds(start, end, segments)
            duration = end - start
            if duration < 5:
                continue  # too short to be useful at all
            if duration > SHORTS_MAX_DURATION:
                # Past a real ceiling, not a soft one - over this and it stops
                # being a Shorts-eligible video at all, regardless of quality.
                oversized += 1
                continue
            valid_clips.append({
                "start": start,
                "end": end,
                "hook_mechanic": c.get("hook_mechanic", "unknown"),
                "title": c.get("title", "Untitled Short")[:100],
                "description": c.get("description", "#Shorts"),
                "reason": c.get("reason", ""),
            })
        except (KeyError, ValueError, TypeError):
            continue

    if oversized:
        print(f"[select_clips] Skipped {oversized} candidate(s) over the {SHORTS_MAX_DURATION:.0f}s Shorts limit.")

    return valid_clips


def _select_clips_for_chunk(
    segments: list[dict],
    max_clips: int,
    model: str,
    min_duration: float,
    max_duration: float,
    performance_hint: str | None = None,
    cancel_event=None,
) -> list[dict]:
    check_cancelled(cancel_event)
    user_prompt = build_user_prompt(segments, max_clips)
    system_prompt = build_system_prompt(min_duration, max_duration, performance_hint)

    raw_text = call_groq(user_prompt, system_prompt, model=model)
    clips = parse_clips_json(raw_text)
    return validate_clips(clips, segments)


def _remaining_chunks_estimate(chunks: list[list[dict]], from_index: int) -> int:
    """Rough token cost of processing chunks[from_index:] plus one rerank pass,
    used to decide whether a fallback model has enough budget left to finish
    a run that a previous model ran out of steam partway through."""
    remaining_chunks = chunks[from_index:]
    return (
        sum(estimate_tokens(s["text"]) + 8 for c in remaining_chunks for s in c)
        + SYSTEM_PROMPT_OVERHEAD_TOKENS * len(remaining_chunks)
        + RERANK_OVERHEAD_TOKENS
    )


def _pick_model_with_budget(fallback_chain: list[str], estimated_tokens: int, exclude: set) -> str | None:
    for candidate in fallback_chain:
        if candidate not in exclude and estimated_tokens <= token_budget.remaining_budget(candidate):
            return candidate
    return None


def select_clips(
    segments: list[dict],
    max_clips: int = 8,
    model: str = MODEL,
    min_duration: float = DEFAULT_MIN_DURATION,
    max_duration: float = DEFAULT_MAX_DURATION,
    allow_model_fallback: bool = True,
    cancel_event=None,
) -> list[dict]:
    chunks = chunk_segments(segments)
    if not chunks:
        return []

    per_chunk_max = max(1, -(-max_clips // len(chunks)))  # ceil(max_clips / len(chunks))
    performance_hint = build_performance_hint()
    if performance_hint:
        print("[select_clips] Found past-upload performance data - biasing selection toward "
              "the hook mechanics that have retained viewers best so far.")

    # Try the requested model first, then fall through to other Groq models -
    # each has its own independent daily budget, so one running out doesn't
    # have to stop the whole day's processing.
    fallback_chain = [model] + [m for m in MODEL_FALLBACK_CHAIN if m != model] if allow_model_fallback else [model]

    estimated_tokens = (
        sum(estimate_tokens(s["text"]) + 8 for s in segments)
        + SYSTEM_PROMPT_OVERHEAD_TOKENS * len(chunks)
        + (RERANK_OVERHEAD_TOKENS if len(chunks) > 1 else 0)
    )
    current_model = _pick_model_with_budget(fallback_chain, estimated_tokens, exclude=set())
    if current_model is None:
        budgets = ", ".join(f"{m}: ~{token_budget.remaining_budget(m):,} left" for m in fallback_chain)
        raise token_budget.GroqBudgetExhausted(
            f"This video needs an estimated ~{estimated_tokens:,} Groq tokens, but no model in "
            f"today's fallback chain has enough left ({budgets})."
        )

    print(f"[select_clips] Asking '{current_model}' (via Groq) to pick up to {max_clips} clips total, "
          f"targeting {min_duration:.0f}-{max_duration:.0f}s each, "
          f"across {len(chunks)} chunk(s)...")

    all_clips: list[dict] = []
    exhausted_models: set = set()
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        if len(chunks) > 1:
            print(f"[select_clips] Chunk {i + 1}/{len(chunks)} ({len(chunk)} segments) "
                  f"using '{current_model}'...")
        try:
            all_clips.extend(
                _select_clips_for_chunk(
                    chunk, per_chunk_max, current_model, min_duration, max_duration,
                    performance_hint, cancel_event,
                )
            )
        except (token_budget.GroqBudgetExhausted, GroqGenerationError) as e:
            print(f"[select_clips] {e}")
            exhausted_models.add(current_model)
            remaining_estimate = _remaining_chunks_estimate(chunks, i)
            next_model = _pick_model_with_budget(fallback_chain, remaining_estimate, exhausted_models)
            if next_model is None:
                raise
            print(f"[select_clips] Switching to '{next_model}' for the remaining chunks...")
            current_model = next_model
            continue  # retry this same chunk with the new model

        i += 1
        if i < len(chunks):
            interruptible_sleep(CHUNK_COOLDOWN_SECONDS, cancel_event)  # stay under the tokens-per-minute limit

    try:
        all_clips = rerank_clips(
            all_clips, max_clips, current_model, min_duration, max_duration, performance_hint, cancel_event
        )
    except (token_budget.GroqBudgetExhausted, GroqGenerationError) as e:
        print(f"[select_clips] {e}")
        next_model = _pick_model_with_budget(fallback_chain, RERANK_OVERHEAD_TOKENS, exhausted_models | {current_model})
        if next_model is None:
            print(f"[select_clips] No model left with budget for the rerank pass; "
                  f"keeping the first {max_clips} candidates unranked.")
            all_clips = all_clips[:max_clips]
        else:
            print(f"[select_clips] Switching to '{next_model}' for the rerank pass...")
            all_clips = rerank_clips(
                all_clips, max_clips, next_model, min_duration, max_duration, performance_hint, cancel_event
            )

    print(f"[select_clips] Got {len(all_clips)} valid clip(s) from the model.")
    return all_clips


def save_plan(video_stem: str, clips: list[dict], out_dir: str = "clips") -> str:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_stem}_plan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clips, f, ensure_ascii=False, indent=2)
    print(f"[select_clips] Saved clip plan -> {out_path}")
    return str(out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript_path", help="Path to transcript JSON from transcribe.py")
    parser.add_argument("--max-clips", type=int, default=8)
    parser.add_argument("--model", default=MODEL, help="Groq model name")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION,
                         help="Target minimum clip length in seconds (default: 30)")
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION,
                         help="Target maximum clip length in seconds (default: 45)")
    args = parser.parse_args()

    segments = load_transcript(args.transcript_path)
    clips = select_clips(
        segments,
        max_clips=args.max_clips,
        model=args.model,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
    )
    video_stem = Path(args.transcript_path).stem
    save_plan(video_stem, clips)
