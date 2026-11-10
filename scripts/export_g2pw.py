"""export_g2pw.py —— 把多音字表导出成 GPT-SoVITS(G2PW) 的词典条目。

背景：GPT-SoVITS 默认 is_g2pw=True，走 BERT 整句推理，然后由
g2pw.correct_pronunciation() 查 polyphonic-fix.rep 做手工覆盖：

    def correct_pronunciation(word, word_pinyins):
        new_pinyins = pp_dict.get(word, "")
        if new_pinyins == "": ... 否则直接 return new_pinyins

所以只要往 polyphonic-fix.rep 里加 `词:['shuai4', 'ling3']`，
就能在不改原文的前提下修正读音——输出文本保持干净，不会出现“帅领”这种错别字。

词典格式（g2pw.read_dict 用 eval 解析）：
    词:['pinyin1', 'pinyin2']

依赖 pypinyin（GPT-SoVITS 环境自带）。

用法：
    # 先看会生成什么
    python scripts/export_g2pw.py

    # 直接写入 GPT-SoVITS 的词典（自动备份 + 跳过已有词）
    python scripts/export_g2pw.py --write "D:/GPT-SoVITS/GPT_SoVITS/text/g2pw/polyphonic-fix.rep"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nvlib


def build_entries() -> tuple[list[tuple[str, list[str]]], list[tuple[str, str]]]:
    """返回 (条目列表, 跳过列表)。拼音是 TONE3 数字声调，与 g2pw 输出格式一致。"""
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        print(
            "缺少 pypinyin。请在 GPT-SoVITS 的 Python 环境里运行，或先装：\n"
            "  pip install pypinyin",
            file=sys.stderr,
        )
        raise SystemExit(3)

    raw = nvlib.load_rules("polyphone")
    rows: list[tuple[str, list[str]]] = []
    skipped: list[tuple[str, str]] = []

    for g in raw.get("groups", []):
        char = g.get("char", "")
        default = g.get("default_reading", "")
        overrides = g.get("readings") or {}
        for word in (g.get("rules") or {}):
            py = overrides.get(word) or default
            base = lazy_pinyin(word, style=Style.TONE3, neutral_tone_with_five=True)
            if len(base) != len(word) or char not in word:
                skipped.append((word, f"拼音数不匹配: {base}"))
                continue
            if py:
                base[word.find(char)] = py
            rows.append((word, base))
    return rows, skipped


def format_line(word: str, pys: list[str]) -> str:
    return f"{word}:{pys}"


def _existing_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" in line:
            keys.add(line.split(":", 1)[0].strip())
    return keys


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="导出 G2PW 多音字词典")
    ap.add_argument("--out", default="polyphonic-fix.append.rep", help="导出的片段文件")
    ap.add_argument("--write", metavar="REP_PATH", help="直接追加到 GPT-SoVITS 的 polyphonic-fix.rep")
    ap.add_argument("--force", action="store_true", help="已存在的词也重新写入")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args(argv)

    rows, skipped = build_entries()
    target = Path(args.write) if args.write else Path(args.out)

    if args.write:
        if not target.exists():
            print(f"[错误] 找不到 {target}\n"
                  f"       确认路径是否指向 GPT-SoVITS 的 GPT_SoVITS/text/g2pw/polyphonic-fix.rep",
                  file=sys.stderr)
            return 2
        backup = target.parent / (target.name + ".bak")
        backup.write_bytes(target.read_bytes())
        print(f"已备份原词典 -> {backup}")

    existing = _existing_keys(target) if args.write else set()
    lines, skipped_dup = [], 0
    for word, pys in rows:
        if word in existing and not args.force:
            skipped_dup += 1
            continue
        lines.append(format_line(word, pys))

    print(f"待写入 {len(lines)} 条（已有跳过 {skipped_dup} 条，格式异常跳过 {len(skipped)} 条）")
    for s in skipped[:5]:
        print(f"  [跳过] {s[0]} {s[1]}")
    print("--- 样例 ---")
    for line in lines[:8]:
        print("  " + line)

    if args.dry_run:
        print("(dry-run，未写文件)")
        return 0

    if args.write:
        if not lines:
            print("没有新条目需要写入。")
            return 0
        with open(target, "a", encoding="utf-8", newline="\n") as f:
            for line in lines:
                f.write(line + "\n")
        print(f"\n已追加 {len(lines)} 条到 {target}")
        print("重启 GPT-SoVITS 即可生效（polyphonic.md5 变了会自动重建缓存，不用手动删）")
    else:
        nvlib.write_text(target, "\n".join(lines) + "\n")
        print(f"\n已导出 -> {target}")
        print("追加命令（Windows PowerShell）：")
        print(f'  Get-Content "{target}" | Add-Content "D:\\GPT-SoVITS\\GPT_SoVITS\\text\\g2pw\\polyphonic-fix.rep"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
