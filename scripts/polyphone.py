"""polyphone.py —— 多音字同音替换。

TTS 读不准多音字时，把词里的多音字换成同音字（率领 -> 帅领），读音就对了。
只做整词替换，词外一个字不动；按词长降序匹配，长词优先。

副作用：替换后的文本仅供朗读，人工阅读会看到错别字。用 --no-polyphone 可关闭。
"""
from __future__ import annotations

import re

import nvlib


class Polyphoner:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.table: dict[str, str] = {}
        self.word_group: dict[str, str] = {}
        self.pattern: re.Pattern | None = None
        self.counts: dict[str, int] = {}
        self.by_char: dict[str, int] = {}
        self.group_notes: dict[str, dict] = {}

        if not enabled:
            return
        raw = nvlib.load_rules("polyphone")
        for g in raw.get("groups", []):
            char = g.get("char", "")
            self.group_notes[char] = {"pinyin": g.get("pinyin", ""), "note": g.get("note", "")}
            for word, repl in (g.get("rules") or {}).items():
                self.table[word] = repl
                self.word_group[word] = char
        if self.table:
            keys = sorted(self.table, key=len, reverse=True)  # 长词优先，避免短词截胡
            self.pattern = re.compile("|".join(re.escape(k) for k in keys))

    def run(self, text: str) -> str:
        if not self.enabled or self.pattern is None or not text:
            return text

        def repl(m: re.Match) -> str:
            w = m.group(0)
            self.counts[w] = self.counts.get(w, 0) + 1
            c = self.word_group.get(w, "")
            if c:
                self.by_char[c] = self.by_char.get(c, 0) + 1
            return self.table[w]

        return self.pattern.sub(repl, text)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def top_words(self, n: int = 20) -> list[tuple[str, str, int]]:
        return sorted(
            ((w, self.table[w], c) for w, c in self.counts.items()),
            key=lambda x: -x[2],
        )[:n]


def summarize(pp: Polyphoner) -> str:
    if not pp.enabled:
        return "- 多音字改写：已关闭（--no-polyphone）"
    if not pp.total:
        return "- 多音字改写：未命中词表中的词"
    detail = "、".join(f"{c} {n}" for c, n in sorted(pp.by_char.items(), key=lambda x: -x[1]))
    return f"- 多音字改写：{pp.total} 处（{detail}）"
