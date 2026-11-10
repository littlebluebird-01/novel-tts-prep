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
    merged: list[str] = field(default_factory=list)   # 被并入本章的原章标题

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


def _split_uniform(paras: list[str], target: int, tolerance: float = 0.15) -> list[list[str]]:
    """按目标字数均分成若干块。

    有声书要求每章音频时长接近，所以不能用“累积到 target 就切”的贪心法——
    那样前面每块正好 target、最后一块只剩零头，偏差能到 40%。
    正确做法是先算要切几份，再把切点放在最接近等分位置的段落边界上。
    """
    counts = [nvlib.count_read_chars(p) for p in paras]
    total = sum(counts)
    if total <= target * (1 + tolerance) or total <= 200 or len(paras) < 2:
        return [paras]

    n = max(2, int(round(total / target)))
    aim = total / n

    cum, acc = [], 0
    for c in counts:
        acc += c
        cum.append(acc)

    # 每个等分点选最靠近它的段落边界；引号没闭合时往后挪一两段
    cuts: list[int] = []
    for k in range(1, n):
        want = aim * k
        best = min(range(len(cum)), key=lambda i: abs(cum[i] - want))
        shift = 0
        while shift < 3 and best + shift < len(paras) - 1:
            head = "\n".join(paras[: best + shift + 1])
            if _quotes_balanced(head):
                break
            shift += 1
        idx = min(best + shift, len(paras) - 2)
        if not cuts or idx > cuts[-1]:
            cuts.append(idx)

    parts: list[list[str]] = []
    start = 0
    for idx in cuts:
        parts.append(paras[start: idx + 1])
        start = idx + 1
    parts.append(paras[start:])
    return [p for p in parts if p]


def reflow(
    sections: list[Chapter],
    target: int = 1500,
    tolerance: float = 0.15,
    unit: str = "章",
) -> list[Chapter]:
    """忽略原章边界，全书按字数重排。

    有声书要每章音频时长接近，原章边界是最大障碍：作者一章 945 字、下一章 3200 字，
    尊重边界就永远均匀不了。重排后每章都贴着 target，代价是丢掉作者的分章标题。
    """
    paras = [p for sec in sections for p in sec.paras if p.strip()]
    if not paras:
        return []
    chunks = _split_uniform(paras, target, tolerance)
    return [
        Chapter(title=f"第{nvlib.int2cn(i + 1)}{unit}", paras=c, origin="")
        for i, c in enumerate(chunks)
    ]


def merge_short_chapters(
    chapters: list[Chapter], target: int = 1500, tolerance: float = 0.15
) -> list[Chapter]:
    """把明显偏短的章并入前一章，合并后不超过目标上限。"""
    if not chapters:
        return chapters
    lo = target * (1 - tolerance)
    hi = target * (1 + tolerance)
    out: list[Chapter] = []
    for ch in chapters:
        if out and ch.chars < lo and out[-1].chars + ch.chars <= hi * 1.02:
            out[-1].paras.extend(ch.paras)
            out[-1].merged.append(ch.title)
            continue
        out.append(ch)
    return out


def rechapter(
    sections: list[Chapter],
    target: int = 3000,
    tolerance: float = 0.15,
    merge_short: bool = False,
    renumber: bool = False,
) -> list[Chapter]:
    """按目标字数重分章。target 是「目标朗读字数」，tolerance 控制允许的偏差。

    有声书要保证每章音频时长接近，所以 target 给 1500 就尽量每章 1500，
    偏差主要来自段落粒度——段落越长，实际每章的波动越大。
    """
    out: list[Chapter] = []

    for sec in sections:
        chars = sec.chars
        if chars <= target * (1 + tolerance) or chars <= 200:
            out.append(sec)
            continue
        chunks = _split_uniform(sec.paras, target, tolerance)
        for i, chunk in enumerate(chunks):
            if i == 0:
                title = sec.title
            else:
                suffix = "（续）" if i == 1 else f"（续{nvlib.int2cn(i)}）"
                title = (sec.title + suffix) if sec.title else ""
            out.append(Chapter(title=title, paras=chunk, origin=sec.title, part=i + 1))

    if merge_short:
        out = merge_short_chapters(out, target, tolerance)

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
