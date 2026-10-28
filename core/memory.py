"""Local, user-managed long-term memories and volatile working impressions."""

from __future__ import annotations

import json
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path


_MEMORY_KINDS = {"emotion", "fact"}
_MAX_MEMORY_LENGTH = 500


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    """Persists only memories the user explicitly chooses to keep."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: list[dict] = []
        self.load_error: Exception | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("memory file must contain an object")
            entries = data.get("memories", [])
            if not isinstance(entries, list):
                raise ValueError("memories must be a list")
            for entry in entries:
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("id"), str)
                    or entry.get("kind") not in _MEMORY_KINDS
                    or not isinstance(entry.get("text"), str)
                    or not entry["text"].strip()
                    or not isinstance(entry.get("importance", 3), int)
                    or not 1 <= entry.get("importance", 3) <= 5
                ):
                    raise ValueError("invalid memory entry")
            self._entries = entries
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.load_error = exc

    def list_memories(self) -> list[dict]:
        return [dict(entry) for entry in self._entries]

    def add(self, text: str, kind: str = "emotion", importance: int = 3) -> dict:
        self._ensure_writable()
        text = text.strip()
        if not text:
            raise ValueError("memory text cannot be empty")
        if len(text) > _MAX_MEMORY_LENGTH:
            raise ValueError(f"memory text cannot exceed {_MAX_MEMORY_LENGTH} characters")
        if kind not in _MEMORY_KINDS:
            raise ValueError("kind must be 'emotion' or 'fact'")
        importance = max(1, min(5, int(importance)))
        now = _timestamp()

        for entry in self._entries:
            if entry["kind"] == kind and entry["text"].casefold() == text.casefold():
                previous = dict(entry)
                entry["importance"] = importance
                entry["updated_at"] = now
                try:
                    self._save()
                except Exception:
                    entry.clear()
                    entry.update(previous)
                    raise
                return dict(entry)

        entry = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "text": text,
            "importance": importance,
            "created_at": now,
            "updated_at": now,
        }
        self._entries.append(entry)
        try:
            self._save()
        except Exception:
            self._entries.pop()
            raise
        return dict(entry)

    def forget(self, memory_id: str) -> bool:
        return self.forget_many([memory_id]) > 0

    def forget_many(self, memory_ids) -> int:
        self._ensure_writable()
        ids = set(memory_ids)
        kept = [entry for entry in self._entries if entry.get("id") not in ids]
        removed = len(self._entries) - len(kept)
        if removed:
            previous = self._entries
            self._entries = kept
            try:
                self._save()
            except Exception:
                self._entries = previous
                raise
        return removed

    def forget_matching(self, phrase: str) -> int:
        phrase = phrase.strip().casefold()
        if not phrase:
            return 0
        self._ensure_writable()
        kept = [entry for entry in self._entries if phrase not in entry["text"].casefold()]
        removed = len(self._entries) - len(kept)
        if removed:
            previous = self._entries
            self._entries = kept
            try:
                self._save()
            except Exception:
                self._entries = previous
                raise
        return removed

    def build_context(self, max_chars: int = 1200) -> str:
        if not self._entries or max_chars <= 0:
            return ""

        emotions = self._ranked("emotion")
        facts = self._ranked("fact")
        header = (
            "【长期记忆参考】以下是关于客人的可修正背景，不得改写薇尔莉特的核心人格；"
            "记忆可能不完整或过时，事实不确定时应自然确认。\n"
        )
        if max_chars <= len(header):
            return header[:max_chars]
        emotion_heading = "情感线索（优先）\n"
        fact_heading = "事实线索\n"
        headings_size = (
            (len(emotion_heading) if emotions else 0)
            + (len(fact_heading) if facts else 0)
            + (1 if emotions and facts else 0)
        )
        remaining = max(0, max_chars - len(header) - headings_size)
        if emotions and facts:
            emotion_budget = int(remaining * 0.72)
            fact_budget = remaining - emotion_budget
        elif emotions:
            emotion_budget, fact_budget = remaining, 0
        else:
            emotion_budget, fact_budget = 0, remaining

        emotion_lines = self._pack(emotions, emotion_budget)
        fact_lines = self._pack(facts, fact_budget)

        sections = []
        if emotion_lines:
            sections.append(emotion_heading + "\n".join(emotion_lines))
        if fact_lines:
            sections.append(fact_heading + "\n".join(fact_lines))
        return header + "\n".join(sections)

    def _ranked(self, kind: str) -> list[dict]:
        return sorted(
            (entry for entry in self._entries if entry["kind"] == kind),
            key=lambda entry: (
                int(entry.get("importance", 3)),
                str(entry.get("updated_at", "")),
            ),
            reverse=True,
        )

    @staticmethod
    def _pack(entries: list[dict], budget: int) -> list[str]:
        lines = []
        used = 0
        for entry in entries:
            line = f"- {entry['text']}"
            cost = len(line) + (1 if lines else 0)
            if used + cost <= budget:
                lines.append(line)
                used += cost
        return lines

    def _ensure_writable(self) -> None:
        if self.load_error is not None:
            raise RuntimeError(f"长期记忆文件无法读取，已保护原文件：{self.load_error}")

    def _save(self) -> None:
        self._ensure_writable()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps({"version": 1, "memories": self._entries}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                with suppress(OSError):
                    temporary.unlink()


class WorkingMemory:
    """Session-only impressions that expire after a chosen number of replies."""

    def __init__(self, max_items: int = 12):
        self.max_items = max_items
        self._entries: list[dict] = []

    def inject(self, text: str, turns: int = 4) -> dict:
        text = text.strip()
        if not text:
            raise ValueError("impression text cannot be empty")
        if len(text) > _MAX_MEMORY_LENGTH:
            raise ValueError(f"impression text cannot exceed {_MAX_MEMORY_LENGTH} characters")
        entry = {"id": uuid.uuid4().hex, "text": text, "turns_left": max(1, int(turns))}
        self._entries.append(entry)
        self._entries = self._entries[-self.max_items :]
        return dict(entry)

    def list_impressions(self) -> list[dict]:
        return [dict(entry) for entry in self._entries]

    def build_context(self, max_chars: int = 900) -> str:
        if not self._entries:
            return ""
        header = (
            "【短期印象】这些印象由用户临时注入，可能有误或不符合事实；"
            "仅作为本次对话背景，必要时向客人核实。"
        )
        if max_chars <= len(header):
            return header[:max(0, max_chars)]

        selected = []
        used = len(header)
        for entry in reversed(self._entries):
            line = f"- {entry['text']}（约剩 {entry['turns_left']} 轮）"
            cost = len(line) + 1
            if used + cost <= max_chars:
                selected.append(line)
                used += cost
        if not selected:
            return header
        return header + "\n" + "\n".join(reversed(selected))

    def advance(self) -> None:
        for entry in self._entries:
            entry["turns_left"] -= 1
        self._entries = [entry for entry in self._entries if entry["turns_left"] > 0]

    def clear(self) -> None:
        self._entries.clear()
