"""chapter.py —— 按目标字数重分章，并输出一章一文件。

原则：
1. 只切不改：章节正文顺序绝对不变。
2. 优先在段落边界切；切点落在引号未闭合处时往后顺延，避免把一句话劈成两半。
3. 保留作者原标题；切出来的续章用“（续）”，不篡改原题。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import nvlib

_OPEN_Q = "“‘「『（(【"
_CLOSE_Q = "”’」』）)】"


@dataclass
class Chapter:
    title: str
    paras: list[str] = field(default_factory=list)
    origin: str = ""
    part: int = 1

    @property
    def chars(self) -> int:
        return nvlib.count_read_chars("\n".join(self.paras))

    def to_text(self, with_title: bool = True) -> str:
        body = "\n\n".join(p for p in self.paras if p.strip())
        if with_title and self.title:
            return f"{self.title}\n\n{body}\n"
        return (body + "\n") if body else ""


def parse_sections(text: str) -> list[Chapter]:
    """按识别到的标题切成章节块。没有标题时整本算一块。"""
    lines = text.split("\n")
    sections: list[Chapter] = []
    cur: Chapter | None = None
    buf: list[str] = []

    def flush():
        nonlocal cur, buf
        if cur is None and buf:
            cur = Chapter(title="", paras=[], origin="")
        if cur is None:
            return
        body = [p for p in buf if p.strip()]
        cur.paras = body
        if cur.title or body:
            sections.append(cur)
        buf = []

    for line in lines:
        s = line.strip()
        if not s:
            continue
        if nvlib.is_heading(s):
            title = nvlib.clean_heading(s)
            # 同一标题连续出现（正文里又贴了一遍），跳过
            if cur is not None and not buf and title == cur.title:
                continue
            flush()
            cur = Chapter(title=title, paras=[], origin=title)
            continue
        buf.append(s)
    flush()

    if not sections:
        return []
    return sections


def _quotes_balanced(text: str) -> bool:
    return sum(text.count(c) for c in _OPEN_Q) == sum(text.count(c) for c in _CLOSE_Q)


def _split_paragraphs(paras: list[str], target: int) -> list[list[str]]:
    """贪心累积到目标字数就切，遇到引号未闭合最多顺延 3 段。"""
    parts: list[list[str]] = []
    buf: list[str] = []
    n = 0
    for p in paras:
        buf.append(p)
        n += nvlib.count_read_chars(p)
        if n < target:
            continue
        if not _quotes_balanced("\n".join(buf)) and len(buf) < len(paras):
            continue
        parts.append(buf)
        buf, n = [], 0
    if buf:
        parts.append(buf)
    # 尾巴太短就跟前一份并了，避免出现 200 字的碎章
    if len(parts) >= 2 and nvlib.count_read_chars("\n".join(parts[-1])) < target * 0.25:
        parts[-2].extend(parts.pop())
    return parts


def rechapter(
    sections: list[Chapter],
    target: int = 3000,
    max_ratio: float = 1.4,
    merge_short: bool = False,
    renumber: bool = False,
) -> list[Chapter]:
    """按目标字数重分章。target 是“目标朗读字数”。"""
    out: list[Chapter] = []

    for sec in sections:
        chars = sec.chars
        if chars <= target * max_ratio or chars <= 200:
            out.append(sec)
            continue
        chunks = _split_paragraphs(sec.paras, target)
        for i, chunk in enumerate(chunks):
            if i == 0:
                title = sec.title
            else:
                suffix = "（续）" if i == 1 else f"（续{nvlib.int2cn(i)}）"
                title = (sec.title + suffix) if sec.title else ""
            out.append(Chapter(title=title, paras=chunk, origin=sec.title, part=i + 1))

    if merge_short:
        out = _merge_short(out, target)

    if renumber:
        for i, ch in enumerate(out, 1):
            ch.title = f"第{nvlib.int2cn(i)}章"

    # 没标题的章统一补编号，保证 TTS 与文件名有序
    counter = 0
    for ch in out:
        if not ch.title:
            counter += 1
            ch.title = f"第{nvlib.int2cn(counter)}章"
    return out


def _merge_short(chapters: list[Chapter], target: int) -> list[Chapter]:
    """把明显过短的章并到前一章（默认关闭，会破坏与原章的一一对应）。"""
    if not chapters:
        return chapters
    out = [chapters[0]]
    for ch in chapters[1:]:
        if ch.chars < target * 0.3 and out[-1].chars + ch.chars < target * 1.5:
            out[-1].paras.extend(ch.paras)
        else:
            out.append(ch)
    return out


def write_chapters(chapters: list[Chapter], outdir: str | Path, digits: int = 4) -> list[dict]:
    """一章一个 txt，文件名 0001_第一章 标题.txt。"""
    d = Path(outdir)
    d.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, ch in enumerate(chapters, 1):
        name = f"{i:0{digits}d}_{nvlib.sanitize_filename(ch.title)}.txt"
        path = d / name
        nvlib.write_text(path, ch.to_text(with_title=True))
        manifest.append({
            "seq": i,
            "title": ch.title,
            "origin": ch.origin,
            "part": ch.part,
            "chars": ch.chars,
            "file": name,
        })
    return manifest
