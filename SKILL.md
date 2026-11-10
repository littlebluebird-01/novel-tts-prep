---
name: novel-tts-prep
version: 1.0.0
display_name: 网文清洗与朗读化
display_name_en: Web Novel Cleanup & TTS Prep
description_zh: |-
  把一本脏的网文 txt 变成可直接朗读的干净分章稿。适用于：去广告去水印、删除重复段落、清乱码、合并被硬折的行、按目标字数重分章、一章一个文件、把数字/货币/分数/日期/单位/英文改写成中文读法（english → 英格丽史、$50 → 五十美元、3/4 → 四分之三），产出处理报告与待复核清单。
  触发词：整理小说、网文清洗、txt 去广告、去重、合并断行、重新分章、按字数分章、转成朗读稿、有声书文本预处理、TTS 文本规范化、英文改中文读法、小说排版。
  不适用：翻译英文小说成中文（本技能只做音译读法，不做语义翻译）、抓取/下载正文、写小说、剧情节选。
description_en: Clean messy web-novel TXT files into chapter-split, TTS-ready scripts — strip ads/watermarks, dedupe paragraphs, fix hard-wrapped lines, re-split by word count, and normalize numbers, currency, fractions, dates, units and English words into spoken Chinese.
---

# 网文清洗与朗读化

把一个脏 txt 处理成「能直接丢给 TTS 朗读」的分章稿。五个动作，全部有确定答案：

| 阶段 | 干什么 | 谁来做 |
| --- | --- | --- |
| 清洗 | 去广告/水印/站点尾巴、删重复段落、清乱码、合并硬折行、统一标点 | 脚本 |
| 朗读化 | 数字、货币、分数、日期、单位、英文词 → 中文读法 | 脚本 |
| 多音字 | 率领→帅领、归还→归环、着急→招急（整词同音替换） | 脚本 |
| 重分章 | 识别原章、切过长的章、按目标字数重整、一章一文件 | 脚本 |
| 复核与润色 | 判断可疑行、确认表外音译、改写机翻腔 | 模型（你） |

## 什么时候用它

- 手里有整本网文 txt，要放进有声书流程或本地阅读器
- 一章几万字，想按 3000 字左右重切
- 正文里全是 `www.xxx.com`、`请记住本站`、`求推荐票`、重复段落
- TTS 读到 `$50`、`3/4`、`english` 就念错或跳过
- txt 被硬折成每行 25 字，段落结构全丢了

**不要用在**：把英文小说翻译成中文（只做音译读法）；从网站抓正文；给小说续写/改写情节；单章随手改几个错别字。

## 一条命令跑完

```bash
python "<skill>/scripts/pipeline.py" run "书.txt" -o out --target 3000
```

`<skill>` 即本技能目录（`~/.workbuddy/skills/novel-tts-prep`）。跑完看 `out/report.md`。

先体检不动手：

```bash
python "<skill>/scripts/pipeline.py" scan "书.txt"
```

只演算不写文件：`run ... --scan-only`。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--target` | 3000 | 每章目标**朗读字数**（有声书一般 1500） |
| `--tolerance` | 0.15 | 每章字数允许偏差；有声书建议 0.1 |
| `--reflow` | 关 | 忽略原章边界全书重排。时长最整齐；标题会跟着内容走，不丢原章名 |
| `--join` | auto | 断行合并：`auto` 检测到一句一行才合并，`always` 强制，`never` 不合并 |
| `--english` | transliterate | `transliterate` 音译（english→英格丽史），`keep` 保留原样 |
| `--fraction` | cn | `cn`=四分之三（标准读法），`user`=三分之四（按分子分母顺序） |
| `--no-dedupe` | 关 | 关闭段落去重（原文有大量刻意重复时用） |
| `--dedupe-near` | 100 | 只删相邻 N 段内的重复，更远的只记录不删 |
| `--dedupe-global` | 关 | 整本去重不限距离（多版本拼接的书用，有误删风险） |
| `--no-polyphone` | 关 | 关闭多音字同音替换。要一份能正常阅读的稿子时加这个 |
| `--renumber` | 关 | 全书重新连续编号，丢弃作者原标题 |
| `--merge-short` | 关 | 把过短的章并入前一章 |
| `--digits` | 4 | 文件名序号位数（`0001_第一章.txt`） |

## 输出物

```
out/
  chapters/0001_第一章 雨夜.txt    # 一章一个文件，标题+正文
  book_clean.txt                   # 全书合并稿
  report.md                        # 处理报告，先看这个
  manifest.json                     # 章序、标题、字数、来源
  uncertain.jsonl                   # 表外英文的近似音译，待复核
  flags.jsonl                       # 可疑行（作者感言/疑似广告），已保留
  dropped_lines.jsonl               # 每条被删内容的审计记录，怀疑误删时查这里
```

`report.md` 末尾有「下一步」，把待办直接列出来了。

## 有声书：字数决定时长

用户做有声书时，第一个要问的是「每章多少字」。给了目标字数后：

- 尊重原章：`--target 1500` → 会尽量切到 1500，但原章本身偏短的改不了（实测标准差 201）
- 要时长整齐：`--target 1500 --tolerance 0.1 --reflow` → 全书重排，标准差能压到 25

`--reflow` 的标题规则：**章号全书连续重编，原标题挪到章号后面**。原章被切成 N 块就加（一）（二），只切一块不加。

```
第一章 一九五八，老饕的噩梦
第二章 【家常菜（入门 50/50）】（一）
第三章 【家常菜（入门 50/50）】（二）
第四章 【转职到大锅饭能手】
```

不加 `--reflow` 时章号会重复（`第一章 XXX（续）`），表示「同一章的后半段」，语义没问题但不连续。

副作用：原书名与简介区会卷进第一章；原书跳号时新旧序号会越差越远。

报告里有「字数分布」一节：最短/最长/平均/标准差/落在目标区间的比例。**先看这节再交活**——标准差过百就说明该上 `--reflow` 或调 `--tolerance`。

## 你该介入的四件事

脚本只做确定性的事。遇到判断题，它会把证据摆到报告里，等你处理。

### 1. 读 report.md 的「下一步」

先看这一段，通常 0–3 条。没有就说明可以直接进 TTS。

### 2. 复查两张词表

**英文音译**（`uncertain.jsonl`）：词表 `scripts/rules/en2zh.json` 里没有的词会走音节兜底，结果是「能念但很怪」：

| 原词 | 兜底结果 | 处理 |
| --- | --- | --- |
| blizzard | 布尔伊兹阿尔德 | 补进 `things` 或 `people` 分组 |
| Sherlock | 舍尔洛克 | 人名建议补表，别让它每次乱猜 |

**多音字**（报告里的「多音字改写」一节）：`polyphone.json` 里没有的词不会被替换，TTS 该怎么错还怎么错。用户反馈某个词读错时，补一条整词映射。

两处都是改 JSON 后重跑，**不要**为了几个词去改代码。

### 3. 复核可疑行（`flags.jsonl`）

`更新说明`、`作者感言`、`疑似广告短行` 这类已保留但标出。确认要删的，直接改 `scripts/rules/ads.json` 的 `drop_lines`，重跑。别手工在输出文件里删——下次重跑会回来。

### 4. 机翻腔润色（唯一需要模型动笔的地方）

脚本默认**一个字都不改**正文。用户要"深度润色"时才做，规则见 `references/polish.md`：

- 一次处理 1–2 章，别整本塞进去
- 只改语言（病句、机翻腔、指代不清、重复用词），不改情节、人设、数字、伏笔
- 保留段落结构，输出改了哪几句的清单
- 拿不准的原文错误只记录，不擅改

百万字全量润色又慢又贵。先读前 3 章判断是否真的机翻腔，再决定范围。

## 规则想改就改

三张表都在 `scripts/rules/`，改完直接重跑，不用碰代码：

| 文件 | 管什么 |
| --- | --- |
| `ads.json` | `drop_lines` 整行删 / `strip_inline` 行内剔 / `flag_lines` 保留但报告 |
| `en2zh.json` | 英文 → 中文读法，按分组。key 小写，匹配不分大小写 |
| `polyphone.json` | 多音字整词替换（`率领→帅领`），按字分组，每条带注音说明 |
| `ads.json` 的 `line_join` | 断行合并的句末标点与长度阈值 |

细则见 `references/rules.md`。

## GPT-SoVITS：可以不改原文

`polyphone` 阶段默认改文本（`率领→帅领`）。如果引擎是 GPT-SoVITS，有更干净的路：它默认走 G2PW 整句推理，再由 `g2pw.correct_pronunciation()` 查 `polyphonic-fix.rep` 覆盖，所以把词表导成词典就行，原文一个字不动。

```bash
python scripts/export_g2pw.py --where   # 先看探测到哪些词典
python scripts/export_g2pw.py           # 找到一处就直接写，多处会列出让你选
```

**不需要用户知道安装路径**，脚本按「环境变量 → 当前目录向上 → 各盘根目录的 `GPT-SoVITS*` / `*sovits*` / `*AudioBook*`」自动探测，0.3 秒出结果。写入前备份 `.bak`，只补词典缺的词；已有条目读音不一致会列出来并覆盖（`--skip-conflicts` 可保留）。重启生效。

前提：用 GPT-SoVITS 自己的 Python 跑（依赖 pypinyin）；`chinese2.py` 里 `is_g2pw = True`（默认）。若是 `False`，走纯 pypinyin 路径，这个词典不生效，只能用默认的同音替换。

## 已知边界

- **多音字替换后的稿子只适合朗读**：`率领→帅领` 这种替换必然留下"错别字"。要能正常阅读的稿子，加 `--no-polyphone` 再跑一次。两份稿子各跑一遍是正常用法。
- 只吃纯文本（txt）。epub/docx 请先转 txt。
- 编码自动识别 UTF-8/GBK/BIG5/UTF-16；识别结果写在报告里。输出统一 UTF-8。
- 分数按标准中文读法 `3/4 → 四分之三`（分母在前）。要反过来用 `--fraction user`。
- 表外英文的兜底音译只是保底，质量不保证，必须复核。
- 去重按「整段内容完全相同」判定，只处理 20 字以上的段落；刻意重复的短句不会被动。
- 原文件只读，绝不覆盖。所有输出写到 `-o` 指定目录。
