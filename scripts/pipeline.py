"""pipeline.py —— 命令行入口。

用法：
  python scripts/pipeline.py scan 书.txt
  python scripts/pipeline.py run  书.txt -o out --target 3000
  python scripts/pipeline.py run  书.txt -o out --target 3000 --scan-only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import chapter as chap
import clean as cleaner
import nvlib
import normalize as norm
import polyphone as poly


def _p(msg: str = "") -> None:
    print(msg, flush=True)


def scan(path: Path) -> dict:
    text, enc = nvlib.read_text(path)
    lines = [l for l in text.split("\n") if l.strip()]
    headings = [l.strip() for l in lines if nvlib.is_heading(l)]
    eng_words = len(re.findall(r"[A-Za-z]+", text))
    digits = len(re.findall(r"\d+", text))
    return {
        "file": str(path),
        "bytes": path.stat().st_size,
        "encoding": enc,
        "lines": len(lines),
        "cjk": nvlib.count_cjk(text),
        "read_chars": nvlib.count_read_chars(text),
        "headings": len(headings),
        "first_headings": headings[:5],
        "english_words": eng_words,
        "number_runs": digits,
    }


def build_report(
    *,
    src: Path,
    info: dict,
    clean_res: cleaner.CleanResult,
    norm_stats: dict,
    uncertain: list[dict],
    manifest: list[dict],
    total_chars: int,
    pp: poly.Polyphoner,
    args,
) -> str:
    s = clean_res.stats
    out = []
    out.append(f"# 处理报告：{src.name}\n")
    out.append("## 总览\n")
    out.append("| 项目 | 数值 |")
    out.append("| --- | --- |")
    out.append(f"| 源文件 | `{src.name}` |")
    out.append(f"| 源编码 | {info['encoding']} |")
    out.append(f"| 原始行数 | {info['lines']} |")
    out.append(f"| 原始朗读字数 | {info['read_chars']} |")
    out.append(f"| 输出朗读字数 | {total_chars} |")
    out.append(f"| 识别原章数 | {info['headings']} |")
    out.append(f"| 输出章数 | {len(manifest)} |")
    out.append(f"| 目标字数/章 | {args.target} |")
    out.append(f"| 英文处理 | {'音译' if args.english == 'transliterate' else '保留'} |")
    out.append(f"| 分数读法 | {'四分之三（标准）' if args.fraction == 'cn' else '三分之四（按序）'} |")
    out.append("")

    out.append("## 清洗\n")
    out.append(f"- 换行风格判定：**{s.get('line_style')}**")
    out.append(f"- 清除乱码/控制字符：{s.get('junk_chars')} 个")
    out.append(f"- 整行删除（广告/水印/站点尾巴）：{s.get('dropped_lines')} 行")
    out.append(f"- 行内剔除广告片段：{s.get('stripped_inline')} 处")
    out.append(f"- 合并硬断行：{s.get('merged_lines')} 行")
    out.append(f"- 重新分段：{s.get('reparagraphed', 0)} 段")
    out.append(f"- 删除重复段落：{s.get('deduped_paragraphs')} 段")
    out.append(f"- 可疑但保留：{s.get('flagged_lines')} 行")
    by_rule = s.get("dropped_by_rule") or {}
    if by_rule:
        out.append("\n删除明细：\n")
        out.append("| 规则 | 命中行数 |")
        out.append("| --- | --- |")
        for k, v in sorted(by_rule.items(), key=lambda x: -x[1]):
            out.append(f"| {k} | {v} |")
    for key, label in (("drop_samples", "删除样例"), ("dedupe_samples", "重复段落样例")):
        rows = s.get(key) or []
        if rows:
            out.append(f"\n{label}（前 {len(rows)} 条）：\n")
            out.append("| 位置 | 内容 |")
            out.append("| --- | --- |")
            for r in rows:
                loc = r.get("line") or r.get("first_seen_para") or "-"
                txt = str(r.get("text", "")).replace("|", "\\|")[:60]
                out.append(f"| {loc} | {txt} |")
    out.append("")

    out.append("## 朗读化\n")
    labels = {
        "dates": "日期", "times": "时间", "currency": "货币", "percent": "百分比",
        "fraction": "分数", "units": "单位", "years": "年份", "numbers": "数字",
        "decimals": "小数", "english_hit": "英文（词表命中）", "english_guess": "英文（兜底音译）",
    }
    hit = [(labels.get(k, k), v) for k, v in norm_stats.items() if v]
    if hit:
        out.append("| 类型 | 处数 |")
        out.append("| --- | --- |")
        for k, v in hit:
            out.append(f"| {k} | {v} |")
    else:
        out.append("无需改写。")
    out.append("")

    if pp.enabled:
        out.append("## 多音字改写\n")
        if pp.total:
            out.append(
                f"共 {pp.total} 处同音替换，涉及 {len(pp.counts)} 个词。"
                "**替换后仅供朗读**，人工阅读会看到错别字；需要干净的阅读稿请加 `--no-polyphone` 重跑一次。\n"
            )
            out.append("| 原文 | 改为 | 次数 | 说明 |")
            out.append("| --- | --- | --- | --- |")
            for w, r, c in pp.top_words(40):
                ch = pp.word_group.get(w, "")
                note = (pp.group_notes.get(ch, {}) or {}).get("pinyin", "")
                out.append(f"| {w} | {r} | {c} | {ch} 读 {note} |")
            if len(pp.counts) > 40:
                out.append(f"\n> 另有 {len(pp.counts) - 40} 个词未列出。")
        else:
            out.append("词表里的词一个都没命中。若书里多音字仍读错，把词补进 `scripts/rules/polyphone.json`。")
        out.append("")

    if uncertain:
        out.append("## 待复核：表外英文音译\n")
        out.append(f"共 {len(uncertain)} 个词走了近似音译，建议扫一眼，把常用词补进 "
                   f"`scripts/rules/en2zh.json`。\n")
        out.append("| 原词 | 近似音译 | 上下文 |")
        out.append("| --- | --- | --- |")
        for u in uncertain[:60]:
            out.append(f"| {u['word']} | {u['guess']} | {u['context'][:40].replace('|', '\\|')} |")
        if len(uncertain) > 60:
            out.append(f"\n> 其余 {len(uncertain) - 60} 条见 `uncertain.jsonl`。")
        out.append("")

    flags = clean_res.flags
    if flags:
        out.append("## 待复核：可疑行\n")
        out.append("这些行可能是作者感言、求票、或漏掉的广告。已保留，请确认是否要删。\n")
        out.append("| 行号 | 类型 | 内容 |")
        out.append("| --- | --- | --- |")
        for f in flags[:40]:
            out.append(f"| {f['line']} | {f['rule']} | {f['text'][:50].replace('|', '\\|')} |")
        if len(flags) > 40:
            out.append(f"\n> 其余 {len(flags) - 40} 条见 `flags.jsonl`。")
        out.append("")

    out.append("## 分章结果\n")
    out.append("| 序号 | 标题 | 字数 | 来源 |")
    out.append("| --- | --- | --- | --- |")
    for m in manifest:
        out.append(f"| {m['seq']} | {m['title'][:40].replace('|', '\\|')} | {m['chars']} | {m['origin'][:20] or '-'} |")
    out.append("")

    shorts = [m for m in manifest if m["chars"] < args.target * 0.3]
    if shorts:
        out.append(f"> 有 {len(shorts)} 章低于目标字数的 30%："
                   + "、".join(f"第{m['seq']}章" for m in shorts[:10])
                   + ("…" if len(shorts) > 10 else ""))
        out.append("")

    out.append("## 下一步\n")
    todo = []
    if uncertain:
        todo.append(f"表外英文 {len(uncertain)} 个走了近似音译，确认后补进 `scripts/rules/en2zh.json`")
    if flags:
        todo.append(f"可疑行 {len(flags)} 行，确认是删除还是保留")
    if shorts:
        todo.append(f"{len(shorts)} 章偏短，如需均衡可考虑 `--merge-short`")
    if args.english == "keep":
        todo.append("本次未做英文音译，若要交 TTS 朗读请加 `--english transliterate`")
    if pp.enabled and pp.total:
        todo.append(f"多音字已替换 {pp.total} 处，此稿只适合朗读；要阅读稿请加 `--no-polyphone` 再跑一次")
    if not todo:
        todo.append("清洗与分章均无待处理项，可直接进 TTS")
    for i, t in enumerate(todo, 1):
        out.append(f"{i}. {t}")
    out.append("")
    return "\n".join(out)


def run(args) -> int:
    src = Path(args.input).expanduser()
    if not src.exists():
        _p(f"[错误] 找不到文件：{src}")
        return 2

    info = scan(src)
    _p(f"源文件：{src.name}  编码 {info['encoding']}  朗读字数 {info['read_chars']}  原章 {info['headings']}")

    text, _ = nvlib.read_text(src)
    clean_res = cleaner.clean_text(
        text,
        join_lines=args.join,
        dedupe=not args.no_dedupe,
    )
    _p(cleaner.summarize(clean_res))

    sections = chap.parse_sections(clean_res.text)
    _p(f"结构识别：{len(sections)} 段")

    nz = norm.Normalizer(fraction=args.fraction, english=args.english)
    for sec in sections:
        sec.paras = [nz.run(p)[0] for p in sec.paras]
        sec.title = nz.run(sec.title, strip_cjk_space=False)[0] if sec.title else ""

    # 多音字替换放在朗读化之后：前面已经把中文之间的空格清掉了，词才能整词命中
    pp = poly.Polyphoner(enabled=not args.no_polyphone)
    if pp.enabled:
        for sec in sections:
            sec.paras = [pp.run(p) for p in sec.paras]
            sec.title = pp.run(sec.title)
        _p(poly.summarize(pp))

    chapters = chap.rechapter(
        sections,
        target=args.target,
        merge_short=args.merge_short,
        renumber=args.renumber,
    )
    total = sum(c.chars for c in chapters)
    _p(f"分章结果：{len(chapters)} 章，合计 {total} 朗读字")

    if args.scan_only:
        for c in chapters[:10]:
            _p(f"  {c.title}  {c.chars} 字")
        _p("（--scan-only：未写文件）")
        return 0

    outdir = Path(args.outdir).expanduser()
    manifest = chap.write_chapters(chapters, outdir / "chapters", digits=args.digits)
    nvlib.write_text(outdir / "book_clean.txt",
                     "\n\n".join(c.to_text() for c in chapters))

    report = build_report(
        src=src, info=info, clean_res=clean_res, norm_stats=nz.stats,
        uncertain=nz.uncertain, manifest=manifest, total_chars=total, pp=pp, args=args,
    )
    nvlib.write_text(outdir / "report.md", report)
    nvlib.write_json(outdir / "manifest.json", manifest)
    nvlib.write_jsonl(outdir / "uncertain.jsonl", nz.uncertain)
    nvlib.write_jsonl(outdir / "flags.jsonl", clean_res.flags)

    _p(f"\n输出目录：{outdir}")
    _p(f"  章节文件 {len(manifest)} 个 -> {outdir / 'chapters'}")
    _p(f"  全书合并稿 -> {outdir / 'book_clean.txt'}")
    _p(f"  处理报告   -> {outdir / 'report.md'}")
    if nz.uncertain:
        _p(f"  待复核词   -> {outdir / 'uncertain.jsonl'}（{len(nz.uncertain)} 条）")
    return 0


def main(argv=None) -> int:
    try:  # Windows 控制台中文
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog="pipeline", description="网文清洗 + 朗读化 + 重分章")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan", help="只体检，不产出文件")
    sp.add_argument("input")

    rp = sub.add_parser("run", help="跑全流程")
    rp.add_argument("input")
    rp.add_argument("-o", "--outdir", default="./out")
    rp.add_argument("--target", type=int, default=3000, help="每章目标朗读字数（默认 3000）")
    rp.add_argument("--join", choices=["auto", "always", "never"], default="auto",
                    help="断行合并策略（默认 auto：检测到一句一行才合并）")
    rp.add_argument("--no-dedupe", action="store_true", help="关闭段落去重")
    rp.add_argument("--no-polyphone", action="store_true",
                    help="关闭多音字同音替换（要干净阅读稿时用）")
    rp.add_argument("--english", choices=["transliterate", "keep"], default="transliterate",
                    help="英文处理：音译（默认）或保留")
    rp.add_argument("--fraction", choices=["cn", "user"], default="cn",
                    help="分数读法：cn=四分之三（标准），user=三分之四（按分子分母顺序）")
    rp.add_argument("--renumber", action="store_true", help="全书重新连续编号，丢弃原标题")
    rp.add_argument("--merge-short", action="store_true", help="把过短的章并入前一章")
    rp.add_argument("--digits", type=int, default=4, help="文件名序号位数（默认 4）")
    rp.add_argument("--scan-only", action="store_true", help="只演算不写文件")

    args = ap.parse_args(argv)
    if args.cmd == "scan":
        import json
        _p(json.dumps(scan(Path(args.input).expanduser()), ensure_ascii=False, indent=2))
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
