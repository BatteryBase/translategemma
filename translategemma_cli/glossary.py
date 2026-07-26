"""Glossary matching, masking, and post-translation enforcement."""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "docs" / "glossary.csv"

_PLACEHOLDER_RE = re.compile(r"⟦G(\d+)⟧")
# Legacy {target} tokens from older masking (still normalized on output).
_BRACE_TOKEN_RE = re.compile(r"\{\s*([^}]+?)\s*\}")
# Strip instruction text if the model echoed a glossary hint into the output.
_INSTRUCTION_LEAK_RE = re.compile(
    r"Important:\s*"
    r"(?:Keep tokens like|Do not change tokens like)\s+"
    r".*?"
    r"do not translate or remove them\.?"
    r"\s*",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class GlossarySession:
    """Tracks placeholders applied to a source text."""

    placeholders: dict[str, str] = field(default_factory=dict)  # ⟦G0⟧ -> English target
    sources: dict[str, str] = field(default_factory=dict)  # Chinese source -> English target
    source_counts: dict[str, int] = field(default_factory=dict)  # occurrences in source text


class Glossary:
    """CSV glossary with longest-first, non-overlapping term matching."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._entries: dict[str, str] = {}
        self._wrongs: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        with self.path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source = (row.get("source") or "").strip()
                target = (row.get("target") or "").strip()
                if source and target:
                    self._entries[source] = target
                    wrong_field = (row.get("wrong") or "").strip()
                    if wrong_field:
                        self._wrongs[source] = [
                            w.strip() for w in re.split(r"[|,]", wrong_field) if w.strip()
                        ]

    @property
    def size(self) -> int:
        return len(self._entries)

    def match(self, text: str) -> list[tuple[str, str]]:
        """Return non-overlapping glossary pairs found in text (longest first)."""
        spans = self._find_spans(text)
        return [(source, target) for _, _, source, target in spans]

    def _find_spans(self, text: str) -> list[tuple[int, int, str, str]]:
        """Find every non-overlapping glossary occurrence (longest match wins per position)."""
        if not text or not self._entries:
            return []

        occupied = [False] * len(text)
        spans: list[tuple[int, int, str, str]] = []

        for source in sorted(self._entries.keys(), key=len, reverse=True):
            target = self._entries[source]
            start = 0
            while start < len(text):
                idx = text.find(source, start)
                if idx == -1:
                    break
                end = idx + len(source)
                if not any(occupied[idx:end]):
                    spans.append((idx, end, source, target))
                    for i in range(idx, end):
                        occupied[i] = True
                start = idx + 1

        spans.sort(key=lambda item: item[0])
        return spans

    def mask_for_translation(self, text: str) -> tuple[str, GlossarySession]:
        """
        Replace every glossary hit with opaque placeholders ⟦G{n}⟧.

        Each distinct occurrence gets its own placeholder so counts are preserved.
        """
        spans = self._find_spans(text)
        if not spans:
            return text, GlossarySession()

        session = GlossarySession()
        parts: list[str] = []
        last = 0

        for i, (start, end, source, target) in enumerate(spans):
            placeholder = f"⟦G{i}⟧"
            session.placeholders[placeholder] = target
            session.sources[source] = target
            session.source_counts[source] = session.source_counts.get(source, 0) + 1

            parts.append(text[last:start])
            parts.append(placeholder)
            last = end

        parts.append(text[last:])
        masked = "".join(parts)
        if session.placeholders:
            self._assert_fully_masked(masked, session)
        return masked, session

    @staticmethod
    def strip_instruction_leak(output: str) -> str:
        """Remove glossary instruction text accidentally translated into the output."""
        cleaned = _INSTRUCTION_LEAK_RE.sub("", output)
        return cleaned.strip()

    def _assert_fully_masked(self, masked: str, session: GlossarySession) -> None:
        """Ensure no raw glossary Chinese remains after masking."""
        for source in session.sources:
            if source in masked:
                raise RuntimeError(f"glossary term not fully masked: {source}")

    def finalize_output(self, output: str, session: GlossarySession) -> str:
        """Restore all placeholders and force glossary English targets."""
        if not output:
            return output

        result = self.strip_instruction_leak(output)
        if not session.placeholders:
            return result
        targets = set(session.placeholders.values())

        # 1) Restore opaque placeholders via regex (covers every ⟦G{n}⟧ occurrence).
        def _placeholder_replacer(match: re.Match[str]) -> str:
            key = f"⟦G{match.group(1)}⟧"
            return session.placeholders.get(key, match.group(0))

        result = _PLACEHOLDER_RE.sub(_placeholder_replacer, result)

        # 2) Restore common placeholder corruptions from the model.
        for placeholder, target in session.placeholders.items():
            index = placeholder[2:-1]  # G0 from ⟦G0⟧
            for variant in (
                f"⟦ G{index} ⟧",
                f"[G{index}]",
                f"(G{index})",
                f"<G{index}>",
                f"G{index}",
                f"{{G{index}}}",
            ):
                result = result.replace(variant, target)

        # 3) Normalize legacy {English target} wrappers.
        def _brace_replacer(match: re.Match[str]) -> str:
            inner = match.group(1).strip()
            return inner if inner in targets else match.group(0)

        result = _BRACE_TOKEN_RE.sub(_brace_replacer, result)

        # 4) Force glossary English targets when the model used a wrong wording.
        # Guard every replace loop: if substitution makes no progress, stop.
        # (Old code matched the canonical target itself with IGNORECASE and spun forever
        # when expected count > actual count, e.g. Charge×2 but only one "Charge" in output.)
        for source, target in sorted(session.sources.items(), key=lambda x: len(x[0]), reverse=True):
            expected = session.source_counts.get(source, 0)
            if expected <= 0:
                continue
            actual = result.count(target)
            if actual >= expected:
                continue

            for wrong in self._wrongs.get(source, []):
                if not wrong or wrong.casefold() == target.casefold():
                    continue
                pattern = re.compile(re.escape(wrong), re.IGNORECASE)
                guard = 0
                while actual < expected and guard < expected + 8:
                    guard += 1
                    if not pattern.search(result):
                        break
                    new_result = pattern.sub(target, result, count=1)
                    if new_result == result:
                        break
                    result = new_result
                    new_actual = result.count(target)
                    if new_actual <= actual:
                        break
                    actual = new_actual

            # Normalize multi-word spaced variants only ("Li-ion  Battery" → "Li-ion Battery").
            # Never run this for single-token targets like "Charge"/"Anode" — that was the hang.
            parts = target.split()
            if actual < expected and len(parts) >= 2:
                spaced = re.compile(
                    r"\s+".join(re.escape(part) for part in parts),
                    re.IGNORECASE,
                )
                guard = 0
                while actual < expected and guard < expected + 8:
                    guard += 1
                    m = spaced.search(result)
                    if not m:
                        break
                    if m.group(0) == target:
                        break
                    new_result = result[: m.start()] + target + result[m.end() :]
                    if new_result == result:
                        break
                    result = new_result
                    new_actual = result.count(target)
                    if new_actual <= actual:
                        break
                    actual = new_actual

        return result

    def apply_input(self, text: str) -> tuple[str, GlossarySession]:
        """Mask glossary terms for translation (alias of mask_for_translation)."""
        return self.mask_for_translation(text)

    def placeholder_spans(self, text: str) -> list[tuple[int, int]]:
        """Return (start, end) spans of ⟦G{n}⟧ tokens — used to avoid splitting mid-token."""
        return [(m.start(), m.end()) for m in _PLACEHOLDER_RE.finditer(text)]

    def is_inside_placeholder(self, pos: int, text: str) -> bool:
        for start, end in self.placeholder_spans(text):
            if start <= pos < end:
                return True
        return False

    def safe_slice(self, text: str, start: int, end: int) -> tuple[str, int]:
        """
        Return text[start:end] adjusted so no placeholder is cut in half.
        Returns (slice_text, adjusted_end).
        """
        spans = self.placeholder_spans(text)
        adjusted_end = end
        for ph_start, ph_end in spans:
            if ph_start < adjusted_end < ph_end:
                adjusted_end = ph_start
            if ph_start < start < ph_end:
                start = ph_end
        if start >= adjusted_end:
            return "", start
        return text[start:adjusted_end], adjusted_end


_cached: Glossary | None = None
_cached_path: Path | None = None


def resolve_glossary_path(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    env_path = os.getenv("GLOSSARY_PATH")
    if env_path:
        return Path(env_path)
    return _DEFAULT_GLOSSARY_PATH


def get_glossary(path: str | Path | None = None) -> Glossary:
    """Return a cached Glossary instance."""
    global _cached, _cached_path
    resolved = resolve_glossary_path(path)
    if _cached is None or _cached_path != resolved:
        _cached = Glossary(resolved)
        _cached_path = resolved
    return _cached


def is_masked_text(text: str) -> bool:
    """True if text already contains glossary placeholders."""
    return bool(_PLACEHOLDER_RE.search(text))


def should_apply_glossary(text: str, use_glossary: bool | None, *, default: bool) -> bool:
    """
    Decide whether to mask glossary terms before translation.

    Any glossary hit in the source text is always masked (unless explicitly disabled).
    """
    if use_glossary is False:
        return False
    if get_glossary().match(text):
        return True
    if use_glossary is True:
        return True
    return default


def split_text_preserving_placeholders(
    text: str,
    max_length: int,
    glossary: Glossary | None = None,
) -> list[str]:
    """Split long text by length without breaking ⟦G{n}⟧ placeholders."""
    if len(text) <= max_length:
        return [text]

    glossary = glossary or get_glossary()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_length, len(text))
        if end < len(text):
            chunk, end = glossary.safe_slice(text, start, end)
        else:
            chunk = text[start:end]
        if not chunk.strip():
            break
        chunks.append(chunk.strip())
        start = end if end > start else start + 1
    return chunks or [text]
