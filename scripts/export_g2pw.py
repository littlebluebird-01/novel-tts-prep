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
    # 自动探测安装位置，看会改哪个文件
    python scripts/export_g2pw.py --where

    # 探测并写入（只找到一处时自动写入；找到多处需 --all 或 --write）
    python scripts/export_g2pw.py
    python scripts/export_g2pw.py --all

    # 手动指定
    python scripts/export_g2pw.py --write "H:/GPT-SoVITS-5090/src/text/g2pw/polyphonic-fix.rep"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import nvlib

DICT_NAME = "polyphonic-fix.rep"
# 标准仓库布局，以及本项目这种 src/ 重构布局
KNOWN_REL = (
    Path("GPT_SoVITS") / "text" / "g2pw" / DICT_NAME,
    Path("src") / "text" / "g2pw" / DICT_NAME,
)
SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", "models", "site-packages", "vendor", "wheels",
    "books", "logs", "bgm", "sfx", "www", "refs", "output", "outputs", "cache",
    "nltk_data", "model_packs", "models_www", "audio", "wav", "tmp", "temp",
}


def _local_roots() -> list[Path]:
    """只返回本机固定盘/可移动盘。盲扫 26 个盘符会被掉线的网络盘拖到几十秒。"""
    if os.name != "nt":
        return [Path.home(), Path("/opt"), Path("/usr/local"), Path("/data")]
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        k32.GetDriveTypeW.restype = ctypes.c_uint
        mask = k32.GetLogicalDrives()
        out = []
        for i in range(26):
            if not mask & (1 << i):
                continue
            letter = chr(65 + i)
            # 2=可移动 3=固定盘；跳过网络盘(4)、光驱(5)、内存盘等
            if k32.GetDriveTypeW(f"{letter}:\\") in (2, 3):
                out.append(Path(f"{letter}:/"))
        return out
    except Exception:
        return [Path(f"{d}:/") for d in "CDEFGH"]


# ---------------- 探测 ----------------

def _walk_for_dict(root: Path, max_depth: int = 3) -> list[Path]:
    """按固定深度 glob 找 g2pw/polyphonic-fix.rep。

    不用 os.walk：安装目录里常有 models/books 等海量小文件，
    walk 一次要几十秒。固定深度 glob 只匹配目录名，快一个数量级。
    """
    hits: list[Path] = []
    for depth in range(max_depth + 1):
        pattern = ("*/" * depth) + f"text/g2pw/{DICT_NAME}"
        try:
            hits.extend(p for p in root.glob(pattern) if p.is_file())
        except (PermissionError, OSError):
            pass
    return hits


def _project_root(dict_path: Path) -> Path | None:
    """polyphonic-fix.rep 往上四层就是项目根：<root>/(src|GPT_SoVITS)/text/g2pw/。"""
    try:
        return dict_path.parent.parent.parent.parent
    except IndexError:
        return None


def discover_dicts() -> list[Path]:
    """按优先级找所有 polyphonic-fix.rep。

    分三段，避免一上来就全盘深扫（安装目录常有 models/ 几万个小文件，会很慢）：
      1. 廉价探测：环境变量、当前目录向上、各盘根目录下的标准布局
      2. 在已命中项目的根目录里补一层（release/<发行版>/src/... 这种）
      3. 一个都没找到，才做全盘浅扫
    """
    found: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp.exists() and rp.is_file() and str(rp) not in seen:
            seen.add(str(rp))
            found.append(rp)

    # --- 1) 廉价探测 ---
    cheap: list[Path] = []
    env = os.environ.get("GPT_SOVITS_HOME")
    if env:
        cheap.append(Path(env))
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        cheap.extend([base, *base.parents])

    project_dirs: list[Path] = []
    for root in _local_roots():
        for pat in ("GPT-SoVITS*", "GPT_SoVITS*", "*SoVITS*", "*sovits*", "*AudioBook*"):
            try:
                project_dirs.extend(p for p in root.glob(pat) if p.is_dir())
            except (PermissionError, OSError):
                pass
    cheap.extend(project_dirs)

    for d in cheap:
        for rel in KNOWN_REL:
            add(d / rel)

    # --- 2) 在已命中的项目根里补扫一层 ---
    for p in list(found):
        root = _project_root(p)
        if root and root.is_dir():
            for hit in _walk_for_dict(root, max_depth=3):
                add(hit)

    # --- 3) 还没找到，全盘浅扫 ---
    if not found:
        for d in project_dirs:
            for hit in _walk_for_dict(d, max_depth=4):
                add(hit)
    return found


def _find_sovits_python(targets: list[Path]) -> Path | None:
    """从词典路径反推 GPT-SoVITS 自带的 python，供缺 pypinyin 时自动切换。"""
    cands: list[Path] = []
    for d in targets:
        root = _project_root(d)
        if not root:
            continue
        cands.append(root / ".venv" / "Scripts" / "python.exe")
        cands.append(root / ".venv" / "bin" / "python")
        cands.append(root / "python" / "python.exe")
        cands.append(root / "runtime" / "python.exe")
        try:
            cands.extend(root.glob("release/*/python/python.exe"))
        except OSError:
            pass
    for c in cands:
        if c.exists():
            return c
    return None


def _ensure_pypinyin(targets: list[Path]) -> bool:
    """当前解释器没有 pypinyin 时，自动切到 GPT-SoVITS 自带的那个重跑。

    用户不必知道该用哪个 Python —— 这本来就是自动探测要解决的问题之一。
    """
    try:
        import pypinyin  # noqa: F401
        return True
    except ImportError:
        pass

    if os.environ.get("_G2PW_REEXEC"):
        print("当前 Python 和 GPT-SoVITS 的 Python 都没有 pypinyin。", file=sys.stderr)
        return False

    py = _find_sovits_python(targets)
    if py:
        print(f"当前 Python 没有 pypinyin，自动切换到 GPT-SoVITS 的：{py}", flush=True)
        os.environ["_G2PW_REEXEC"] = "1"
        os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])

    print(
        "这个脚本需要 pypinyin。三种办法任选：\n"
        "  1) 用 GPT-SoVITS 的 Python 跑：<GPT-SoVITS>/.venv/Scripts/python.exe "
        "scripts/export_g2pw.py\n"
        "  2) pip install pypinyin\n"
        "  3) 用 --write 指定词典路径（仍需 pypinyin 生成读音）",
        file=sys.stderr,
    )
    return False


# ---------------- 生成条目 ----------------

def build_entries() -> tuple[list[tuple[str, list[str]]], list[tuple[str, str]]]:
    """返回 (条目列表, 跳过列表)。拼音是 TONE3 数字声调，与 g2pw 输出格式一致。"""
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        print(
            "缺少 pypinyin。请用 GPT-SoVITS 自己的 Python 跑这个脚本，例如：\n"
            "  <GPT-SoVITS>/.venv/Scripts/python.exe scripts/export_g2pw.py\n"
            "  <GPT-SoVITS>/release/<发行目录>/python/python.exe scripts/export_g2pw.py\n"
            "或先 pip install pypinyin",
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
    return f"{word}: {pys}"      # 冒号后留空格，与本项目现有词典风格一致


def load_dict(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def classify(rows, existing) -> tuple[list, list, list]:
    """分成：缺失 / 冲突（已有但读音不同）/ 一致。"""
    missing, conflicts, same = [], [], []
    for word, pys in rows:
        cur = existing.get(word)
        if cur is None:
            missing.append((word, pys))
            continue
        try:
            cur_list = eval(cur)      # g2pw 就是这么读的
        except Exception:
            conflicts.append((word, cur, pys))
            continue
        if cur_list == pys:
            same.append(word)
        else:
            conflicts.append((word, cur_list, pys))
    return missing, conflicts, same


# ---------------- 写入 ----------------

def apply_to(path: Path, rows, existing, fix_conflicts: bool) -> tuple[int, int]:
    missing, conflicts, _ = classify(rows, existing)
    lines = [format_line(w, p) for w, p in missing]
    if fix_conflicts:
        lines += [format_line(w, p) for w, _c, p in conflicts]
    if not lines:
        return 0, len(conflicts)

    backup = path.parent / (path.name + ".bak")
    backup.write_bytes(path.read_bytes())

    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if path.stat().st_size and not path.read_bytes().endswith(b"\n"):
            f.write("\n")
        for line in lines:
            f.write(line + "\n")
    return len(lines) - (len(conflicts) if fix_conflicts else 0), len(conflicts)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="导出 G2PW 多音字词典")
    ap.add_argument("--where", action="store_true", help="只显示探测到的词典位置")
    ap.add_argument("--write", metavar="REP_PATH", help="手动指定 polyphonic-fix.rep")
    ap.add_argument("--all", action="store_true", help="写入所有探测到的词典（多个副本时用）")
    ap.add_argument("--out", default="polyphonic-fix.append.rep", help="仅导出片段文件时用")
    ap.add_argument("--skip-conflicts", action="store_true", help="已有但读音不同的条目不动")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args(argv)

    # 1) 定位目标
    if args.write:
        targets = [Path(args.write).expanduser()]
        if not targets[0].exists():
            print(f"[错误] 找不到 {targets[0]}", file=sys.stderr)
            return 2
    else:
        targets = discover_dicts()
        if not targets:
            print("没探测到 GPT-SoVITS 的 polyphonic-fix.rep。\n"
                  "请用 --write 指定路径，例如：\n"
                  '  --write "D:/GPT-SoVITS/GPT_SoVITS/text/g2pw/polyphonic-fix.rep"',
                  file=sys.stderr)
            return 2
        if len(targets) > 1 and not args.all:
            print(f"探测到 {len(targets)} 处词典：")
            for i, t in enumerate(targets):
                n = len(load_dict(t))
                print(f"  [{i}] {t}  ({n} 条)")
            print("\n它们可能是不同副本。用 --all 全部写入，或 --write 指定其中一个。")
            return 0

    if args.where:
        for t in targets:
            print(f"{t}  ({len(load_dict(t))} 条)")
        return 0

    # 2) 确保 pypinyin 可用（必要时自动切换解释器）
    if not _ensure_pypinyin(targets):
        return 3

    # 3) 生成条目
    rows, skipped = build_entries()
    print(f"词表 {len(rows)} 条" + (f"，格式异常 {len(skipped)} 条" if skipped else ""))

    # 3) 逐个写入
    total_added = total_fixed = 0
    for t in targets:
        existing = load_dict(t)
        missing, conflicts, same = classify(rows, existing)
        print(f"\n目标：{t}")
        print(f"  现有 {len(existing)} 条 | 已一致 {len(same)} | 待新增 {len(missing)} | 读音冲突 {len(conflicts)}")
        if conflicts and not args.skip_conflicts:
            print("  冲突（现有 -> 应改为），会追加覆盖：")
            for w, cur, exp in conflicts[:10]:
                print(f"    {w}: {cur} -> {exp}")
            if len(conflicts) > 10:
                print(f"    ...另有 {len(conflicts) - 10} 条")
        if args.dry_run:
            continue
        added, fixed = apply_to(t, rows, existing, not args.skip_conflicts)
        total_added += added
        total_fixed += fixed
        print(f"  已写入 {added} 条新增" + (f" + {fixed} 条修正" if fixed else "") + f"（原文件备份为 {t.name}.bak）")

    if args.dry_run:
        print("\n(dry-run，未写文件)")
        return 0

    # 4) 只导出片段（用户想自己合并）
    if not targets:
        nvlib.write_text(Path(args.out), "\n".join(format_line(w, p) for w, p in rows) + "\n")

    print("\n重启 GPT-SoVITS 生效（polyphonic.md5 变了会自动重建缓存，不用手动删 pickle）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
