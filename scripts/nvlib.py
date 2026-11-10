"""nvlib —— novel-tts-prep 公共工具层。

只依赖标准库。提供：规则加载、编码探测读写、中文数字读法、章节标题识别、文件名清洗。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent / "rules"

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
DIGITS_CN = "零一二三四五六七八九"

# ---------- 规则 ----------

_cache: dict[str, dict] = {}


def load_rules(name: str) -> dict:
    """加载 rules/<name>.json，带缓存。"""
    if name in _cache:
        return _cache[name]
    path = RULES_DIR / f"{name}.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _cache[name] = data
    return data


def compile_rules(entries: list[dict]) -> list[tuple[str, re.Pattern]]:
    """把 [{'name':..,'pattern':..,'flags':..}] 编译成 [(name, compiled)]。"""
    out = []
    for e in entries or []:
        flags = 0
        f = e.get("flags", "")
        if "i" in f:
            flags |= re.IGNORECASE
        if "m" in f:
            flags |= re.MULTILINE
        if "s" in f:
            flags |= re.DOTALL
        try:
            out.append((e.get("name", "unnamed"), re.compile(e["pattern"], flags)))
        except re.error as exc:  # 规则表写坏时不要让整条流水线崩掉
            print(f"[warn] 规则 {e.get('name')} 正则无效，已跳过: {exc}")
    return out


# ---------- 编码 ----------

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16")


def read_text(path: str | Path) -> tuple[str, str]:
    """读取文本，返回 (内容, 使用的编码)。按 BOM 优先，再依次严格尝试。"""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def write_text(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path: str | Path, obj) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def write_jsonl(path: str | Path, rows: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------- 中文数字 ----------


def int2cn(n: int) -> str:
    """整数 -> 中文读法（数值读法）。12345 -> 一万二千三百四十五"""
    if n < 0:
        return "负" + int2cn(-n)
    if n == 0:
        return "零"
    if n < 10:
        return DIGITS_CN[n]
    if n < 20:
        return "十" + (DIGITS_CN[n % 10] if n % 10 else "")
    if n < 100:
        return DIGITS_CN[n // 10] + "十" + (DIGITS_CN[n % 10] if n % 10 else "")
    if n < 1000:
        rest = n % 100
        head = DIGITS_CN[n // 100] + "百"
        if rest == 0:
            return head
        if rest < 10:
            return head + "零" + DIGITS_CN[rest]
        return head + int2cn(rest)
    if n < 10_000:
        rest = n % 1000
        head = DIGITS_CN[n // 1000] + "千"
        if rest == 0:
            return head
        if rest < 100:
            return head + "零" + int2cn(rest)
        return head + int2cn(rest)
    if n < 10**8:
        return int2cn(n // 10_000) + "万" + _cn_tail(n % 10_000)
    if n < 10**12:
        return int2cn(n // 10**8) + "亿" + _cn_tail(n % 10**8)
    return int2cn(n // 10**12) + "万亿" + _cn_tail(n % 10**12)


def _cn_tail(rest: int) -> str:
    if rest == 0:
        return ""
    if rest < 1000:  # 一亿零五、一万零五百，都要补“零”
        return "零" + int2cn(rest)
    return int2cn(rest)


def digits2cn(s: str) -> str:
    """逐位读。1998 -> 一九九八。非数字字符原样保留。"""
    return "".join(DIGITS_CN[int(c)] if c.isdigit() else c for c in s)


def decimal2cn(s: str) -> str:
    """3.14 -> 三点一四"""
    if "." not in s:
        return int2cn(int(s))
    a, b = s.split(".", 1)
    head = int2cn(int(a)) if a else "零"
    return head + "点" + digits2cn(b)


# ---------- 章节标题 ----------

_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9０-９一二三四五六七八九十百千万零两]{1,8}\s*[章节節回卷部集篇話话]"
    r"|(?:序章|序言|序|楔子|引子|引|尾声|尾聲|终章|終章|后记|後記|番外|外传|外傳|大结局|大結局|尾声|前言|附录)"
    r"|chapter\s*\d+"
    r")"
)


def is_heading(line: str, max_len: int = 45) -> bool:
    """判断一行是否像章节标题。

    严一点：整行不能太长、不能带句末标点，避免把“第一章就写错了。”当成标题。
    """
    s = line.strip()
    if not s or len(s) > max_len:
        return False
    if s[-1] in "。！？，、；：,.;:!?":
        return False
    if s.count("。") or s.count("！") or s.count("？"):
        return False
    return bool(_HEADING_RE.match(s))


def clean_heading(line: str) -> str:
    """标题行去掉首尾装饰符号，保留原文样式。"""
    s = line.strip()
    s = re.sub(r"^[\s\-=*~#◇◆☆★·—…]+", "", s)
    s = re.sub(r"[\s\-=*~#◇◆☆★·—…]+$", "", s)
    return s.strip()


# ---------- 杂项 ----------


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text))


def count_read_chars(text: str) -> int:
    """朗读字数：中文字 + 数字串按 1 个算 + 字母词按 1 个算，用来估算音频时长与分章。"""
    cjk = len(CJK_RE.findall(text))
    nums = len(re.findall(r"\d+", text))
    words = len(re.findall(r"[A-Za-z]+", text))
    return cjk + nums + words


def sanitize_filename(name: str, limit: int = 80) -> str:
    """清掉 Windows 非法字符，截断长度，保留可读性。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", name).strip()
    s = s.strip(". ")
    s = re.sub(r"\s+", " ", s)
    if len(s) > limit:
        s = s[:limit].rstrip()
    return s or "untitled"
