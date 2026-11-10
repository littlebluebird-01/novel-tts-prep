# novel-tts-prep · 网文清洗与朗读化

把一本脏的网文 TXT 处理成能直接交给 TTS 朗读、也能直接阅读的**分章稿**。

四件事一次做完：**去广告去重 → 朗读化改写 → 按字数重分章 → 一章一个文件**。

> Clean messy web-novel TXT into TTS-ready, chapter-split scripts — strip ads, dedupe paragraphs, merge hard-wrapped lines, re-split by word count, and turn numbers / currency / fractions / dates / units / English words into spoken Chinese.

---

## 一分钟判断适不适合你

| ✅ 适合 | ❌ 不适合 |
| --- | --- |
| 整本网文 TXT → TTS 朗读稿 | 英文小说译成中文（只做音译读法，不做语义翻译） |
| 去掉站点水印、`www.xxx.com`、盗版站尾巴 | 从网站抓正文（只处理本地文件，不联网） |
| 删掉前后重复粘贴的整段 | 校对错别字、查情节漏洞、挑逻辑矛盾 |
| 一章几万字，按 3000 字左右重切 | epub / docx / mobi（请先转 txt） |
| `$50`、`3/4`、`english` 改中文读法 | 续写、改情节、调文风（润色有红线，见 `references/polish.md`） |
| GBK 乱码文件转 UTF-8 | 单章改几个错字（用编辑器更快） |
| 被硬折成每行 25 字的 TXT 还原段落 | 图片、漫画、字幕文件 |

拿不准就先跑体检，它不写任何文件：

```bash
python scripts/pipeline.py scan "书.txt"
```

输出的编码、字数、识别到的章节数，一看就知道这书能不能处理。

---

## 它解决什么

网上扒下来的 txt 通常长这样：

```
请记住本书首发域名：www.biquge-xxx.com，最新章节请访问本站。
　　他算了算兜里的钱，$50 大约够买 3/4 个面包，可昨天又涨价 50%。
　　手机用户请浏览 m.biquge-xxx.com 阅读最新章节
求推荐票！求收藏！（本章完）
```

TTS 读到 `$50`、`3/4`、`english` 就念错或直接跳过；广告每隔几段念一遍；一章几万字，读起来没有断点。

跑完就变成：

```
他算了算兜里的钱，五十美元大约够买四分之三个面包，可昨天又涨价百分之五十。
```

### 实际转换效果

| 原文 | 输出 |
| --- | --- |
| `请记住本书首发域名：www.biquge-xxx.com，最新章节请访问本站。` | 整行删除 |
| `求推荐票！求收藏！（本章完）` | 剔除，剩渣二次判定后删除 |
| `$50` / `3/4` / `50%` | `五十美元` / `四分之三` / `百分之五十` |
| `english` / `hello` / `okay` | `英格丽史` / `哈喽` / `欧克` |
| `2020-01-01，晚上12:30` | `二零二零年一月一日，晚上十二点三十分` |
| `5km` / `零下 20℃` | `五公里` / `零下二十摄氏度` |
| `010-88886666` | `零一零、八八八八六六六六`（加顿号，避免连读） |
| `2元` / `24小时` | `两元` / `二十四小时` |
| 一句一行被硬折的 txt | 合并回段落，再按句重分段到 100–150 字 |

---

## 设计原则

**脚本做确定性工作，模型只做判断题。**

- 正则能命中的（站点水印、纯域名行、重复段落、乱码）→ 脚本删，快且可复现
- 需要判断的（这条是广告还是作者感言？这个词该音译成什么？）→ 一律保留 + 写进报告，等人或模型决定

一个刻意的取舍：**拿不准的一律不删**。删错正文用户很难发现，多留几行广告他一眼就能看见。

---

## 安装

```bash
git clone https://github.com/littlebluebird-01/novel-tts-prep.git \
  ~/.workbuddy/skills/novel-tts-prep
```

纯 Python 标准库，无第三方依赖。Python ≥ 3.9。

也可以直接下载后丢进 `~/.workbuddy/skills/` 目录，WorkBuddy 会自动识别为一个技能。

---

## 用法

```bash
# 先体检，不产出文件
python scripts/pipeline.py scan "书.txt"

# 全流程
python scripts/pipeline.py run "书.txt" -o out --target 3000
```

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--target` | 3000 | 每章目标**朗读字数** |
| `--join` | auto | 断行合并：`auto` 检测到一句一行才合并，`always` 强制，`never` 不合并 |
| `--english` | transliterate | `transliterate` 音译，`keep` 保留原样 |
| `--fraction` | cn | `cn`=四分之三（标准），`user`=三分之四（按分子分母顺序） |
| `--no-dedupe` | 关 | 关闭段落去重 |
| `--renumber` | 关 | 全书重新连续编号，丢弃原标题 |
| `--merge-short` | 关 | 过短的章并入前一章 |
| `--digits` | 4 | 文件名序号位数 |
| `--scan-only` | 关 | 演算但不写文件 |

### 输出

```
out/
  chapters/0001_第一章 雨夜.txt    # 一章一个文件
  book_clean.txt                   # 全书合并稿
  report.md                        # 处理报告，先看这个
  manifest.json                     # 章序、标题、字数、来源
  uncertain.jsonl                   # 表外英文的近似音译，待复核
  flags.jsonl                       # 可疑行（已保留）
```

`report.md` 末尾有「下一步」，把待办直接列了出来。

---

## 性能

88 万字、无章节标题的书，9 秒跑完，自动切成 289 章，每章 2295–3090 字（目标 3000）。

---

## 规则可改，不用改代码

三张 JSON 在 `scripts/rules/`：

| 文件 | 管什么 |
| --- | --- |
| `ads.json` | `drop_lines` 整行删 / `strip_inline` 行内剔 / `flag_lines` 保留但报告 |
| `en2zh.json` | 英文 → 中文读法，约 300 条常用词，按分组维护 |

你的书里高频人名不在词表里，会走音节兜底（`blizzard → 布尔伊兹阿尔德`），结果会列进 `uncertain.jsonl`。补进 JSON 重跑即可，比改算法划算。

细则见 `references/rules.md`。

---

## 已知边界

- 只吃纯文本 txt。epub/docx 请先转 txt。
- 编码自动识别 UTF-8 / GBK / BIG5 / UTF-16，输出统一 UTF-8。
- **不做英译中语义翻译**，只做音译读法。
- 分数默认标准读法 `3/4 → 四分之三`（分母在前）。
- 表外英文的兜底音译只是保底，质量不保证，必须复核。
- 去重只判「20 字以上整段完全相同」，刻意重复的短句不会被动。
- 原文件只读，绝不覆盖。

---

## 机翻腔润色

脚本默认**一个字都不改**正文。若要润色，由模型按章分批做，规则见 `references/polish.md`：只换说法不换内容，不改情节、数字、伏笔，一次 1–2 章，输出改动清单。

百万字全量润色成本很高，建议先润前 10 章试读再定范围。

---

## License

MIT
