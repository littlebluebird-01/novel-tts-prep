"""clean.py —— 去广告、去重、清乱码、统标点、合并硬断行。

只做确定性清理，不改写正文句子。所有判断都以“会不会伤到正文”为第一优先：
拿不准的一律进 flag（保留 + 报告），而不是直接删。
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import nvlib

# HTML 标签
_TAG_RE = re.compile(r"</?(?:br|p|div|span|font|b|i|u|strong|em|hr|img|a)\b[^>]*>", re.I)
# 控制字符 / 零宽字符 / 私用区 / 替换符
_JUNK_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
    r"\u200b-\u200f\u202a-\u202e\u2060\ufeff"
    r"\ufffd\ue000-\uf8ff]"
)
# 中文之间的空白
_CJK_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fff])[ \t\u00a0\u3000]+(?=[\u4e00-\u9fff])")
# 中文语境里的半角标点
_HALF_PUNCT_RE = re.compile(r"(?<=[\u4e00-\u9fff])\s*([,.!?;:])\s*(?=[\u4e00-\u9fff])")
_HALF2FULL = {",": "，", ".": "。", "!": "！", "?": "？", ";": "；", ":": "："}
# 长串重复字符（“！！！！！”这类），只收不打散
_REPEAT_RE = re.compile(r"([^\s\u4e00-\u9fff])\1{9,}")


@dataclass
class CleanResult:
    text: str
    stats: dict = field(default_factory=dict)
    samples: list[dict] = field(default_factory=list)
    flags: list[dict] = field(default_factory=list)


def clean_text(
    raw: str,
    join_lines: str = "auto",
    dedupe: bool = True,
    strip_inline: bool = True,
    keep_flags: bool = True,
) -> CleanResult:
    rules = nvlib.load_rules("ads")
    drop_rules = nvlib.compile_rules(rules.get("drop_lines", []))
    strip_rules = nvlib.compile_rules(rules.get("strip_inline", []))
    flag_rules = nvlib.compile_rules(rules.get("flag_lines", []))
    lj = rules.get("line_join", {})
    end_punct = set(lj.get("end_punct", "。！？…”』」）】》!?~～.．"))
    min_len = int(lj.get("min_len", 12))
    max_merged = int(lj.get("max_merged_len", 800))

    stats = {
        "junk_chars": 0,
        "dropped_lines": 0,
        "dropped_by_rule": {},
        "stripped_inline": 0,
        "flagged_lines": 0,
        "merged_lines": 0,
        "deduped_paragraphs": 0,
        "dedupe_samples": [],
        "line_style": "",
    }
    flags: list[dict] = []

    # 1) 实体与标签
    text = html.unescape(raw)
    text = _TAG_RE.sub("\n", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2) 乱码字符
    text, n = _JUNK_CHAR_RE.subn("", text)
    stats["junk_chars"] += n
    text, n = _REPEAT_RE.subn(lambda m: m.group(1) * 3, text)
    stats["junk_chars"] += n

    lines = text.split("\n")
    kept: list[str] = []

    # 3) 行级过滤
    for idx, line in enumerate(lines, 1):
        s = line.strip()

        if not s:
            kept.append("")
            continue

        # 3a) 整行丢弃
        hit = None
        for name, pat in drop_rules:
            if pat.search(s):
                hit = name
                break
        if hit:
            stats["dropped_lines"] += 1
            stats["dropped_by_rule"][hit] = stats["dropped_by_rule"].get(hit, 0) + 1
            if len(stats.setdefault("drop_samples", [])) < 12:
                stats["drop_samples"].append({"rule": hit, "text": s[:80], "line": idx})
            continue

        # 3b) 行内剔除片段
        if strip_inline:
            before = s
            for _, pat in strip_rules:
                s = pat.sub("", s)
            s = re.sub(r"\s{2,}", " ", s).strip()
            if s != before:
                stats["stripped_inline"] += 1
                if not s:  # 剔完变空行，说明整行都是广告
                    stats["dropped_lines"] += 1
                    continue
                # 剔完可能只剩“（本章完）”这类尾巴，再查一次整行规则
                hit2 = next((n for n, p in drop_rules if p.search(s)), None)
                if hit2:
                    stats["dropped_lines"] += 1
                    stats["dropped_by_rule"][hit2] = stats["dropped_by_rule"].get(hit2, 0) + 1
                    continue

        # 3c) 可疑但保留
        for name, pat in flag_rules:
            if pat.search(s):
                stats["flagged_lines"] += 1
                flags.append({"line": idx, "rule": name, "text": s[:100]})
                break

        kept.append(s)

    # 4) 断行合并
    style = _detect_line_style([x for x in kept if x], end_punct)
    stats["line_style"] = style
    if join_lines == "always" or (join_lines == "auto" and style == "hard_wrap"):
        kept, merged = _join_hard_wrapped(kept, end_punct, min_len, max_merged, flag_rules)
        stats["merged_lines"] = merged
        # 硬折行合并后容易出现几百字的巨段，按句重新分段，给 TTS 留出停顿
        kept = _resplit_long(kept)
        stats["reparagraphed"] = sum(1 for p in kept if p.strip())

    # 5) 段落去重
    paras = [p for p in kept]
    if dedupe:
        paras, dups = _dedupe(paras, min_len=20)
        stats["deduped_paragraphs"] = dups["count"]
        stats["dedupe_samples"] = dups["samples"]

    # 6) 空白与标点规整
    out_lines: list[str] = []
    blank = False
    for p in paras:
        p = p.strip()
        if not p:
            if not blank and out_lines:
                out_lines.append("")
                blank = True
            continue
        blank = False
        p = _CJK_SPACE_RE.sub("", p) if not nvlib.is_heading(p) else p
        p = _HALF_PUNCT_RE.sub(lambda m: _HALF2FULL[m.group(1)], p)
        p = re.sub(r"[ \t]{2,}", " ", p)
        out_lines.append(p)

    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    stats["output_lines"] = len(out_lines)
    return CleanResult(text="\n".join(out_lines), stats=stats, flags=flags)


def _detect_line_style(lines: list[str], end_punct: set[str]) -> str:
    """判断原文是一句一行（hard_wrap）还是正常分段（paragraph）。

    依据：有多少行以句末标点收尾。网文 txt 被硬折行时，大量行结尾是逗号或没有标点。
    """
    sample = lines[:2000]
    if not sample:
        return "paragraph"
    ended = sum(1 for s in sample if s and s[-1] in end_punct)
    ratio = ended / max(1, len(sample))
    avg_len = sum(len(s) for s in sample) / max(1, len(sample))
    if ratio < 0.35 and avg_len < 60:
        return "hard_wrap"
    return "paragraph"


def _join_hard_wrapped(
    lines: list[str], end_punct: set[str], min_len: int, max_merged: int,
    flag_rules: list[tuple[str, re.Pattern]],
) -> tuple[list[str], int]:
    out: list[str] = []
    buf = ""
    merged = 0
    for s in lines:
        if not s:
            if buf:
                out.append(buf)
                buf = ""
            out.append("")
            continue
        if nvlib.is_heading(s):
            if buf:
                out.append(buf)
                buf = ""
            out.append(s)
            continue
        is_ad_like = any(pat.search(s) for _, pat in flag_rules)
        if buf and not is_ad_like and len(buf) < max_merged:
            buf += s
            merged += 1
            if s and s[-1] in end_punct:
                out.append(buf)
                buf = ""
            continue
        if buf:
            out.append(buf)
        buf = s
        if s and s[-1] in end_punct and len(s) >= min_len:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out, merged


_SENT_SPLIT_RE = re.compile(r"[^。！？…‥!?]+[。！？…‥]+[”』」）】]?|[^。！？…‥!?]+$")


def _resplit_long(paras: list[str], limit: int = 150) -> list[str]:
    """把合并出来的超长段落按句切成 100~150 字一段。只用于硬折行文本。"""
    out: list[str] = []
    for p in paras:
        s = p.strip()
        if not s or len(s) <= limit:
            out.append(p)
            continue
        sents = [x for x in _SENT_SPLIT_RE.findall(s) if x.strip()]
        buf = ""
        for sent in sents:
            if buf and len(buf) + len(sent) > limit:
                out.append(buf)
                buf = sent
            else:
                buf = (buf + sent) if buf else sent
        if buf:
            out.append(buf)
    return out


def _dedupe(paras: list[str], min_len: int = 20) -> tuple[list[str], dict]:
    """整本范围内去掉完全重复的段落。只对足够长的段落生效，避免误伤短对话。"""
    seen: dict[str, int] = {}
    out: list[str] = []
    count = 0
    samples: list[dict] = []
    for p in paras:
        s = p.strip()
        if not s:
            out.append(p)
            continue
        key = re.sub(r"[\s\W_]+", "", s)
        if len(key) >= min_len and key in seen:
            count += 1
            if len(samples) < 8:
                samples.append({"text": s[:80], "first_seen_para": seen[key]})
            continue
        if len(key) >= min_len:
            seen[key] = len(out)
        out.append(p)
    return out, {"count": count, "samples": samples}


def summarize(result: CleanResult) -> str:
    s = result.stats
    lines = [
        f"- 换行风格判定：{s.get('line_style')}",
        f"- 清理乱码/控制字符：{s.get('junk_chars')} 个",
        f"- 删除广告行：{s.get('dropped_lines')} 行",
        f"- 行内剔除广告片段：{s.get('stripped_inline')} 处",
        f"- 合并硬断行：{s.get('merged_lines')} 行",
        f"- 重新分段：{s.get('reparagraphed', 0)} 段",
        f"- 删除重复段落：{s.get('deduped_paragraphs')} 段",
        f"- 可疑但保留（待复核）：{s.get('flagged_lines')} 行",
    ]
    by_rule = s.get("dropped_by_rule") or {}
    if by_rule:
        lines.append("- 删除明细：" + "，".join(f"{k} {v}" for k, v in by_rule.items()))
    return "\n".join(lines)
