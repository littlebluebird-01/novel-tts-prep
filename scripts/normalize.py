"""normalize.py —— 朗读化（text normalization）。

目标：让 TTS 能把每一个字符都念成自然中文。
处理的顺序很关键，先长结构（日期/时间/货币/单位），再分数，再小数，最后整数与英文。

用户偏好：英文一律音译（english -> 英格丽史），生僻词音译后标 uncertain 供复核。
"""
from __future__ import annotations

import re

import nvlib

# ---------------- 音节音译表（辅音 + 元音合成一个汉字） ----------------
# 逐字母映射会把 bug 念成「布-乌-格」，按音节合成才是「巴-格」。
_CONSONANTS = set("bcdfghjklmnpqrstvwxyz")
_VOWELS = set("aeiou")

_CV = {
    "ba": "巴", "be": "贝", "bi": "比", "bo": "博", "bu": "布",
    "ca": "卡", "ce": "塞", "ci": "西", "co": "科", "cu": "库",
    "da": "达", "de": "德", "di": "迪", "do": "多", "du": "杜",
    "fa": "法", "fe": "费", "fi": "菲", "fo": "福", "fu": "夫",
    "ga": "加", "ge": "格", "gi": "吉", "go": "戈", "gu": "古",
    "ha": "哈", "he": "赫", "hi": "希", "ho": "霍", "hu": "胡",
    "ja": "贾", "je": "杰", "ji": "吉", "jo": "乔", "ju": "朱",
    "ka": "卡", "ke": "凯", "ki": "基", "ko": "科", "ku": "库",
    "la": "拉", "le": "莱", "li": "利", "lo": "洛", "lu": "卢",
    "ma": "马", "me": "梅", "mi": "米", "mo": "莫", "mu": "穆",
    "na": "纳", "ne": "内", "ni": "尼", "no": "诺", "nu": "努",
    "pa": "帕", "pe": "佩", "pi": "皮", "po": "波", "pu": "普",
    "qua": "夸", "que": "奎", "qui": "奎", "quo": "阔",
    "ra": "拉", "re": "雷", "ri": "里", "ro": "罗", "ru": "鲁",
    "sa": "萨", "se": "塞", "si": "西", "so": "索", "su": "苏",
    "ta": "塔", "te": "特", "ti": "蒂", "to": "托", "tu": "图",
    "va": "瓦", "ve": "维", "vi": "维", "vo": "沃", "vu": "武",
    "wa": "瓦", "we": "韦", "wi": "威", "wo": "沃", "wu": "伍",
    "xa": "克萨", "xe": "泽", "xi": "克西", "xo": "佐", "xu": "克苏",
    "ya": "亚", "ye": "耶", "yi": "伊", "yo": "约", "yu": "尤",
    "za": "扎", "ze": "泽", "zi": "齐", "zo": "佐", "zu": "祖",
}

# u 在闭音节（后面还跟辅音）读 /ʌ/，接近 a：bug -> 巴格、bus -> 巴斯、cut -> 卡特
_CV_U_CLOSED = {
    "bu": "巴", "cu": "卡", "du": "达", "fu": "法", "gu": "加",
    "hu": "哈", "ju": "贾", "ku": "卡", "lu": "拉", "mu": "马",
    "nu": "纳", "pu": "帕", "ru": "拉", "su": "萨", "tu": "塔",
    "vu": "瓦", "zu": "扎", "qu": "夸", "xu": "克萨", "yu": "亚",
}

# r 音节与常见词尾
_R_SYL = {"ar": "阿", "er": "尔", "ir": "尔", "or": "奥", "ur": "尔", "yr": "尔"}

_TRIGRAPHS = [
    ("tion", "申"), ("sion", "申"), ("ture", "彻"), ("ough", "奥"),
    ("igh", "艾"), ("ing", "英"), ("ble", "波"), ("ple", "普尔"),
]

_DIGRAPHS = [
    ("th", "思"), ("sh", "什"), ("ch", "奇"), ("ph", "夫"), ("wh", "沃"),
    ("ck", "克"), ("ng", "恩"), ("qu", "夸"), ("ll", "尔"), ("ss", "斯"),
    ("tt", "特"), ("pp", "普"), ("mm", "姆"), ("nn", "恩"), ("rr", "尔"),
    ("dd", "德"), ("gg", "格"), ("bb", "布"), ("ff", "夫"), ("zz", "兹"),
    ("ee", "伊"), ("ea", "伊"), ("oo", "乌"), ("ou", "奥"), ("ow", "奥"),
    ("oa", "欧"), ("ai", "艾"), ("ay", "艾"), ("ei", "艾"), ("ey", "艾"),
    ("oi", "奥伊"), ("aw", "奥"), ("ew", "尤"), ("au", "奥"), ("ue", "尤"),
]

_SINGLE = {
    "a": "阿", "b": "布", "c": "克", "d": "德", "e": "埃", "f": "夫",
    "g": "格", "h": "赫", "i": "伊", "j": "杰", "k": "克", "l": "尔",
    "m": "姆", "n": "恩", "o": "欧", "p": "普", "q": "夸", "r": "尔",
    "s": "斯", "t": "特", "u": "乌", "v": "维", "w": "沃", "x": "克斯",
    "y": "伊", "z": "兹",
}

_UNITS = {
    "km/h": "公里每小时", "kmh": "公里每小时", "km": "公里", "kg": "公斤",
    "cm": "厘米", "mm": "毫米", "ml": "毫升", "mg": "毫克",
    "kwh": "千瓦时", "kw": "千瓦", "hz": "赫兹",
    "gb": "吉", "mb": "兆", "tb": "太", "kb": "千",
    "℃": "摄氏度", "°c": "摄氏度", "°": "度",
    "㎡": "平方米", "m²": "平方米", "m³": "立方米", "m3": "立方米",
}


def _looks_like_abbrev(word: str) -> bool:
    """判断是不是缩写、评级或符号——这类保留原样，音译反而听不懂。

    LV / SSS / XP（全大写）、mx / fg / jpg（没有元音读不出来）、ma / ka（辅音+元音的两三字母）
    都是保留；bug / bank / Sherlock 这种能读成音节词的才音译。
    """
    w = word.strip()
    if not w:
        return True
    if len(w) == 1:
        return True
    if w.isupper():
        return True
    low = w.lower()
    if not re.search(r"[aeiouy]", low):
        return True
    if 2 <= len(low) <= 3 and low[-1] in "aeiou":
        return True
    return False


class Normalizer:
    def __init__(self, fraction: str = "cn", english: str = "transliterate") -> None:
        self.fraction = fraction  # cn=四分之三（标准） / user=三分之四（按分子分母顺序）
        self.english = english    # transliterate / keep
        self.stats = {
            "dates": 0, "times": 0, "currency": 0, "percent": 0, "fraction": 0,
            "units": 0, "years": 0, "numbers": 0, "decimals": 0,
            "english_hit": 0, "english_guess": 0, "english_kept": 0,
        }
        self.uncertain: list[dict] = []
        self._table = self._build_table()

    # ---------------- 表 ----------------
    @staticmethod
    def _build_table() -> dict[str, str]:
        raw = nvlib.load_rules("en2zh")
        table: dict[str, str] = {}
        for key, val in raw.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            for k, v in val.items():
                table[k.lower()] = v
        return table

    def _lookup(self, word: str) -> str | None:
        w = word.lower()
        if w in self._table:
            return self._table[w]
        for suf in ("s", "es", "ed", "ing", "d", "ly", "er", "est"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                base = w[: -len(suf)]
                if base in self._table:
                    return self._table[base]
        return None

    def guess(self, word: str) -> str:
        """按音节近似音译：bug -> 巴格，不是逐字母的「布乌格」。

        质量只够「念得出来」，所以一律进 uncertain 等人工确认。
        """
        w = word.lower()
        out: list[str] = []
        i, n = 0, len(w)
        while i < n:
            hit = False
            for src, dst in _TRIGRAPHS:
                if w.startswith(src, i):
                    out.append(dst)
                    i += len(src)
                    hit = True
                    break
            if hit:
                continue

            # r 音节 er/ar/or/ur：Sherlock -> 什尔洛克、Gordon -> 戈尔登
            if i + 1 < n and w[i + 1] == "r" and w[i:i + 2] in _R_SYL:
                out.append(_R_SYL[w[i:i + 2]])
                i += 2
                continue

            for src, dst in _DIGRAPHS:
                if w.startswith(src, i):
                    out.append(dst)
                    i += len(src)
                    hit = True
                    break
            if hit:
                continue

            # 辅音 + 元音合成一个音节
            if i + 1 < n and w[i] in _CONSONANTS and w[i + 1] in _VOWELS:
                key = w[i:i + 2]
                syl = _CV.get(key)
                if syl:
                    # u 后面还跟辅音是闭音节，读 /ʌ/：bug、bus、cut
                    if w[i + 1] == "u" and i + 2 < n and w[i + 2] not in _VOWELS:
                        syl = _CV_U_CLOSED.get(key, syl)
                    out.append(syl)
                    i += 2
                    continue

            ch = w[i]
            if ch in _VOWELS:
                out.append({"a": "阿", "e": "埃", "i": "伊", "o": "欧", "u": "乌"}[ch])
            else:
                out.append(_SINGLE.get(ch, ""))
            i += 1

        s = "".join(out)
        s = re.sub(r"(.)\1+", r"\1", s)   # 去掉连续重复汉字
        return s or word

    # ---------------- 主流程 ----------------
    def run(self, text: str, strip_cjk_space: bool = True) -> tuple[str, dict, list[dict]]:
        t = text

        # 1) 日期 2020-01-01 / 2020/1/1 / 2020年1月1日
        t = re.sub(
            r"(?<!\d)(\d{4})\s*[-/年\.]\s*(\d{1,2})\s*[-/月\.]\s*(\d{1,2})\s*日?(?!\d)",
            self._date, t,
        )
        # 2) 时间 12:30 / 12:30:45
        t = re.sub(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)", self._time, t)
        # 3) 百分比
        t = re.sub(r"(\d+(?:\.\d+)?)\s*[%％]", self._percent, t)
        # 4) 货币
        t = re.sub(r"[\$＄]\s?(\d[\d,]*(?:\.\d+)?)", lambda m: self._money(m, "美元"), t)
        t = re.sub(r"[￥¥]\s?(\d[\d,]*(?:\.\d+)?)", lambda m: self._money(m, "元"), t)
        t = re.sub(r"£\s?(\d[\d,]*(?:\.\d+)?)", lambda m: self._money(m, "英镑"), t)
        t = re.sub(r"€\s?(\d[\d,]*(?:\.\d+)?)", lambda m: self._money(m, "欧元"), t)
        t = re.sub(r"(?<!\d)(\d[\d,]*(?:\.\d+)?)\s*(USD|RMB|CNY|EUR|GBP)\b",
                   lambda m: self._money_suffix(m), t, flags=re.I)
        # 5) 单位（长的先匹配）
        t = re.sub(
            r"(?<!\d)(\d+(?:\.\d+)?)\s*(km/h|kmh|kwh|kw|km|kg|cm|mm|ml|mg|gb|mb|tb|kb|hz|℃|°C|°|㎡|m²|m³|m3)(?![a-zA-Z])",
            self._unit, t, flags=re.I,
        )
        # 6) 分数 3/4
        t = re.sub(r"(?<![\d/\.])(\d{1,3})\s*/\s*(\d{1,3})(?![\d/\.])", self._fraction, t)
        # 7) 数值区间 3~5 / 3-5；长数字间的连字符（电话、编号）直接去掉
        t = re.sub(r"(\d)\s*[~～]\s*(\d)", r"\1到\2", t)
        t = re.sub(r"(?<!\d)(\d+)\s*[-－—]\s*(\d+)(?!\d)", self._dash, t)
        # 8) 年份 1998年
        t = re.sub(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})\s*年", self._year, t)
        # 9) 运算符（要在整数转换之前）
        for src, dst in (("+", "加"), ("×", "乘"), ("÷", "除以"), ("=", "等于")):
            t = re.sub(rf"(\d)\s*{re.escape(src)}\s*(\d)", rf"\1{dst}\2", t)
        # 9.5) “2” 接量词读“两”：2元 -> 两元
        t = re.sub(
            r"(?<!第)(?<![\d.])2(?=\s*(?:元|个|次|天|年|只|条|张|位|名|件|斤|米|人|页|章|分|秒"
            r"|小时|倍|层|楼|本|支|把|场|回|句|声|步|口|碗|杯|瓶|根|片|块|双|对|套|辆|架|艘"
            r"|颗|粒|滴|座|间|门|户))",
            "两", t,
        )
        # 10) 序数 1st / 2nd
        t = re.sub(r"(?<!\w)(\d{1,3})(st|nd|rd|th)(?!\w)", self._ordinal, t, flags=re.I)
        # 11) 小数
        t = re.sub(r"(?<![\d.])(\d+\.\d+)(?![\d.])", self._decimal, t)
        # 12) 千分位与整数
        t = re.sub(r"(?<!\d)\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)", self._thousand, t)
        t = re.sub(r"\d+", self._int, t)
        # 13) 英文
        if self.english == "transliterate":
            t = self._english_pass(t)
        # 14) 残留符号
        t = self._symbols(t)
        # 15) 收尾空格（标题调用时保留“第一章 雨夜”这种间隔）
        if strip_cjk_space:
            t = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff，。！？；：、）】」』”])", "", t)
        t = re.sub(r"([，。！？；：、])\s+", r"\1", t)
        t = re.sub(r"[ \t]{2,}", " ", t)
        # 16) 成对的半角引号 -> 中文引号
        t = _pair_quotes(t)
        return t, self.stats, self.uncertain

    # ---------------- 回调 ----------------
    def _date(self, m: re.Match) -> str:
        self.stats["dates"] += 1
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        return f"{nvlib.digits2cn(y)}年{nvlib.int2cn(mo)}月{nvlib.int2cn(d)}日"

    def _time(self, m: re.Match) -> str:
        self.stats["times"] += 1
        h, mi = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 24 and 0 <= mi <= 59):
            return m.group(0)
        out = f"{nvlib.int2cn(h)}点"
        if mi:
            out += f"{nvlib.int2cn(mi)}分"
        if m.group(3):
            out += f"{nvlib.int2cn(int(m.group(3)))}秒"
        return out

    def _percent(self, m: re.Match) -> str:
        self.stats["percent"] += 1
        return "百分之" + nvlib.decimal2cn(m.group(1))

    def _money(self, m: re.Match, unit: str) -> str:
        self.stats["currency"] += 1
        return nvlib.decimal2cn(m.group(1).replace(",", "")) + unit

    def _money_suffix(self, m: re.Match) -> str:
        self.stats["currency"] += 1
        unit = {"USD": "美元", "RMB": "元", "CNY": "元", "EUR": "欧元", "GBP": "英镑"}[m.group(2).upper()]
        return nvlib.decimal2cn(m.group(1).replace(",", "")) + unit

    def _unit(self, m: re.Match) -> str:
        key = m.group(2).lower()
        unit = _UNITS.get(key)
        if not unit:
            return m.group(0)
        self.stats["units"] += 1
        return nvlib.decimal2cn(m.group(1)) + unit

    def _fraction(self, m: re.Match) -> str:
        a, b = int(m.group(1)), int(m.group(2))
        if b == 0 or a > 1000 or b > 1000:
            return m.group(0)
        self.stats["fraction"] += 1
        if self.fraction == "user":  # 按“分子分母”直读，非标准但可按需切换
            return f"{nvlib.int2cn(a)}分之{nvlib.int2cn(b)}"
        # 50/50、3/2 这类多半是比值或进度，读“比”比读“分之”自然
        if a >= b:
            return f"{nvlib.int2cn(a)}比{nvlib.int2cn(b)}"
        return f"{nvlib.int2cn(b)}分之{nvlib.int2cn(a)}"

    def _year(self, m: re.Match) -> str:
        self.stats["years"] += 1
        return nvlib.digits2cn(m.group(1)) + "年"

    def _ordinal(self, m: re.Match) -> str:
        self.stats["numbers"] += 1
        return "第" + nvlib.int2cn(int(m.group(1)))

    def _decimal(self, m: re.Match) -> str:
        self.stats["decimals"] += 1
        a, b = m.group(1).split(".")
        return nvlib.int2cn(int(a)) + "点" + nvlib.digits2cn(b)

    def _thousand(self, m: re.Match) -> str:
        s = m.group(0).replace(",", "")
        self.stats["numbers"] += 1
        return nvlib.decimal2cn(s) if "." in s else nvlib.int2cn(int(s))

    def _int(self, m: re.Match) -> str:
        s = m.group(0)
        self.stats["numbers"] += 1
        # 长串（电话/编号）与前导零，逐位读
        if len(s) >= 8 or (len(s) > 1 and s[0] == "0"):
            return nvlib.digits2cn(s)
        return nvlib.int2cn(int(s))

    def _english_pass(self, text: str) -> str:
        # 先处理表中含空格的短语（thank you 之类）
        phrases = sorted((k for k in self._table if " " in k), key=len, reverse=True)
        for p in phrases:
            text = re.sub(rf"(?<![A-Za-z]){re.escape(p)}(?![A-Za-z])",
                          lambda _m, v=self._table[p]: v, text, flags=re.I)

        def repl(m: re.Match) -> str:
            word = m.group(0)
            hit = self._lookup(word)
            if hit:
                self.stats["english_hit"] += 1
                return hit
            # 缩写/评级/读不出来的字母组合保留原样，交给 TTS 读字母
            if _looks_like_abbrev(word):
                self.stats["english_kept"] += 1
                return word
            guess = self.guess(word)
            self.stats["english_guess"] += 1
            if len(self.uncertain) < 400:
                start = max(0, m.start() - 12)
                self.uncertain.append({
                    "type": "english_guess",
                    "word": word,
                    "guess": guess,
                    "context": text[start:m.end() + 12].replace("\n", " "),
                })
            return guess

        return re.sub(r"[A-Za-z]+(?:['’][A-Za-z]+)?", repl, text)

    def _dash(self, m: re.Match) -> str:
        """3-5 -> 三到五；010-88886666 -> 零一零、八八八八六六六六（加停顿，别连读成一串）。"""
        a, b = m.group(1), m.group(2)
        if len(a) <= 2 and len(b) <= 2:
            return f"{a}到{b}"
        return f"{a}、{b}"

    def _symbols(self, text: str) -> str:
        table = {
            "&": "和", "@": "艾特", "#": "号", "→": "到",
            "§": "", "¶": "", "←": "", "\\": "",
        }
        for k, v in table.items():
            text = text.replace(k, v)
        text = text.replace("*", "").replace("_", "")
        return text


def _pair_quotes(text: str) -> str:
    """段内半角双引号成对时，交替换成中文引号；不成对就原样不动。"""
    if text.count('"') < 2 or text.count('"') % 2:
        return text
    out, opening = [], True
    for ch in text:
        if ch == '"':
            out.append("“" if opening else "”")
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


def normalize_text(text: str, fraction: str = "cn", english: str = "transliterate"):
    return Normalizer(fraction=fraction, english=english).run(text)


def summarize(stats: dict, uncertain: list[dict]) -> str:
    parts = [f"{k} {v}" for k, v in stats.items() if v]
    lines = ["- 数字转读：" + ("，".join(parts) if parts else "无")]
    if uncertain:
        lines.append(f"- 表外英文（已近似音译，建议复核）：{len(uncertain)} 个")
    return "\n".join(lines)
