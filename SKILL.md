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

把一个脏 txt 处理成「能直接丢给 TTS 朗读」的分章稿。四个动作，全部有确定答案：

| 阶段 | 干什么 | 谁来做 |
| --- | --- | --- |
| 清洗 | 去广告/水印/站点尾巴、删重复段落、清乱码、合并硬折行、统一标点 | 脚本 |
| 朗读化 | 数字、货币、分数、日期、单位、英文词 → 中文读法 | 脚本 |
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
| `--target` | 3000 | 每章目标**朗读字数**（中文 1 字算 1） |
| `--join` | auto | 断行合并：`auto` 检测到一句一行才合并，`always` 强制，`never` 不合并 |
| `--english` | transliterate | `transliterate` 音译（english→英格丽史），`keep` 保留原样 |
| `--fraction` | cn | `cn`=四分之三（标准读法），`user`=三分之四（按分子分母顺序） |
| `--no-dedupe` | 关 | 关闭段落去重（原文有大量刻意重复时用） |
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
```

`report.md` 末尾有「下一步」，把待办直接列出来了。

## 你该介入的四件事

脚本只做确定性的事。遇到判断题，它会把证据摆到报告里，等你处理。

### 1. 读 report.md 的「下一步」

先看这一段，通常 0–3 条。没有就说明可以直接进 TTS。

### 2. 复核表外英文（`uncertain.jsonl`）

词表 `scripts/rules/en2zh.json` 里没有的词会走音节兜底，结果是「能念但很怪」，例如：

| 原词 | 兜底结果 | 处理 |
| --- | --- | --- |
| blizzard | 布尔伊兹阿尔德 | 补进 `things` 或 `people` 分组 |
| Sherlock | 舍尔洛克 | 人名建议补表，别让它每次乱猜 |

做法：把 REPL 里出现过的常用词补进 JSON，重跑一次即可。**不要**为了几个词去改代码。

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
| `ads.json` 的 `line_join` | 断行合并的句末标点与长度阈值 |

细则见 `references/rules.md`。

## 已知边界

- 只吃纯文本（txt）。epub/docx 请先转 txt。
- 编码自动识别 UTF-8/GBK/BIG5/UTF-16；识别结果写在报告里。输出统一 UTF-8。
- 分数按标准中文读法 `3/4 → 四分之三`（分母在前）。要反过来用 `--fraction user`。
- 表外英文的兜底音译只是保底，质量不保证，必须复核。
- 去重按「整段内容完全相同」判定，只处理 20 字以上的段落；刻意重复的短句不会被动。
- 原文件只读，绝不覆盖。所有输出写到 `-o` 指定目录。
