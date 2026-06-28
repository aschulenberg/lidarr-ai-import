from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MatchCandidate:
    """One possible (album release, track) home for a file, across the artist's
    whole discography - not just the album Lidarr originally guessed. This is what
    lets the AI see "this song exists as a Single, on an EP, AND on the Album"
    side by side instead of only seeing one of them."""

    index: int
    album_id: int
    album_title: str
    album_type: str  # Album / EP / Single / Broadcast / Other
    release_id: int
    release_title: str
    release_date: str | None
    track_id: int
    track_title: str
    track_number: int | None
    disc_number: int | None
    duration_seconds: float | None
    rejections: list[str] = field(default_factory=list)

    def duration_delta(self, file_duration: float | None) -> float | None:
        if file_duration is None or self.duration_seconds is None:
            return None
        return round(abs(file_duration - self.duration_seconds), 2)

    def to_prompt_dict(self, file_duration: float | None) -> dict:
        return {
            "candidate_index": self.index,
            "album_title": self.album_title,
            "album_type": self.album_type,
            "release_title": self.release_title,
            "release_date": self.release_date,
            "track_title": self.track_title,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "track_duration_seconds": self.duration_seconds,
            "duration_delta_seconds": self.duration_delta(file_duration),
            "lidarr_rejection_reasons": self.rejections or None,
        }


@dataclass
class Decision:
    action: str  # "apply" | "needs_review" | "skip"
    candidate_index: int | None
    confidence: float
    reasoning: str

    @classmethod
    def needs_review(cls, reasoning: str) -> "Decision":
        return cls(action="needs_review", candidate_index=None, confidence=0.0, reasoning=reasoning)


DEFAULT_TASK_DESCRIPTION = """You are disambiguating a music file for a Lidarr library import.

A song can legitimately be released more than once for the same artist - as a \
standalone Single, on an EP, and later on a full Album - each with its own release \
and track entry. Lidarr's automatic importer could not confidently pick one, often \
exactly because of this single/EP/album overlap. Your job is to pick the SPECIFIC \
candidate (by candidate_index) that this exact file belongs to, using the evidence below."""

_PROMPT_TEMPLATE = """{task_description}

Track duration is the strongest signal: a delta of more than ~5 seconds is \
strong evidence AGAINST a candidate even if the title matches exactly. Title and \
wording (e.g. "Radio Edit", "Live", "Remix", "Remaster") matter too.

If two or more candidates are genuinely indistinguishable from this evidence, or no \
candidate is a confident match, respond with action "needs_review" rather than guessing.

TARGET EVIDENCE:
{file_evidence}

CANDIDATES:
{candidates}

Respond with ONLY a JSON object, no markdown fences, no commentary, matching exactly:
{{"action": "apply" | "needs_review" | "skip", "candidate_index": <int or null>, \
"confidence": <float 0.0-1.0>, "reasoning": "<one or two sentences>"}}

Use "skip" only if none of the candidates are plausible at all (e.g. wrong artist/song \
entirely).
"""


def build_prompt(
    file_info: dict,
    candidates: list[MatchCandidate],
    task_description: str = DEFAULT_TASK_DESCRIPTION,
    extra_context: str = "",
) -> str:
    file_duration = file_info.get("duration_seconds")
    file_evidence = dict(file_info)
    if extra_context:
        file_evidence["additional_context"] = extra_context
    return _PROMPT_TEMPLATE.format(
        task_description=task_description,
        file_evidence=json.dumps(file_evidence, indent=2, default=str),
        candidates=json.dumps(
            [c.to_prompt_dict(file_duration) for c in candidates], indent=2, default=str
        ),
    )


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_decision(raw_text: str) -> Decision:
    text = raw_text.strip()
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return Decision.needs_review(f"AI response was not parseable JSON: {text[:200]}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return Decision.needs_review(f"AI response JSON parse error: {exc}; raw: {text[:200]}")

    action = data.get("action")
    if action not in ("apply", "needs_review", "skip"):
        return Decision.needs_review(f"AI returned unknown action {action!r}")

    return Decision(
        action=action,
        candidate_index=data.get("candidate_index"),
        confidence=float(data.get("confidence") or 0.0),
        reasoning=str(data.get("reasoning") or ""),
    )


class AIProvider(ABC):
    def __init__(self, model: str, api_key: str, base_url: str | None = None):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    @abstractmethod
    def _complete(self, prompt: str) -> str:
        """Send the prompt, return raw text content of the model's reply."""

    def decide(
        self,
        *,
        file_info: dict,
        candidates: list[MatchCandidate],
        task_description: str = DEFAULT_TASK_DESCRIPTION,
        extra_context: str = "",
    ) -> Decision:
        if not candidates:
            return Decision.needs_review("No candidates to evaluate")
        prompt = build_prompt(file_info, candidates, task_description, extra_context)
        raw = self._complete(prompt)
        decision = parse_decision(raw)
        if decision.candidate_index is not None and not any(
            c.index == decision.candidate_index for c in candidates
        ):
            return Decision.needs_review(
                f"AI picked candidate_index {decision.candidate_index} which doesn't exist"
            )
        return decision
