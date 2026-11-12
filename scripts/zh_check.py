#!/usr/bin/env python3
"""中文写作机械检查。

用法：python3 -I zh_check.py 文件1 [文件2 ……]

每个文件输出两段：
  硬命中：违反硬规则的位置，逐行列出。任一文件有硬命中或出错，退出码为 1。
  计数：汉字总数和几项需要人工判断的指标，附每千字密度，不影响退出码。

检查前的预处理：
  - 跳过围栏代码块（``` 或 ~~~，按开头符号的个数匹配闭合）、缩进式代码块、
    HTML 注释、<pre>/<script>/<style>/<textarea> 块和 highlight shortcode；
  - 去掉行内代码、图片、裸 URL、HTML 标签和 Hugo shortcode，链接只留文字；
  - 表格按单元格检查，跳过表头分隔行；
  - front matter（+++ 或 ---）只检查 title 和 description 的值，没有闭合时报错；
  - 去掉文件开头的 BOM。

不带参数运行时打印本说明，退出码为 2。
"""
import pathlib
import re
import sys
import unicodedata
from collections import namedtuple

# ---------------------------------------------------------------------------
# 字符类与占位符

HAN = "\u3007\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f"
H = f"[{HAN}]"
HAS_HAN = re.compile(H)

# 去掉的结构留下占位符：加粗规则把它们当标点看（goldmark 正是这样处理
# 代码和链接边界的），其余规则检查前再删掉。
CODE_MARK = "\ue000"  # 行内代码
EDGE_MARK = "\ue001"  # 链接、图片、HTML 标签、shortcode、注释的边界

# ---------------------------------------------------------------------------
# 行内清理

CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}")
COMMENT = re.compile(r"<!--.*?-->")
_TEXT = r"(?:[^\[\]]|\[[^\[\]]*\])*"
_DEST = (r"\s*(?:<[^<>\n]*>|(?:[^()\s]|\([^()\s]*\))*)"
         r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*")
IMAGE = re.compile(rf"!\[{_TEXT}\](?:\({_DEST}\)|\[[^\[\]]*\])?")
LINK = re.compile(rf"\[({_TEXT})\]\({_DEST}\)")
REF_LINK = re.compile(r"\[([^\[\]]+)\]\[[^\[\]]*\]")
AUTOLINK = re.compile(r"<(?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*|[^<>\s@]+@[^<>\s@]+)>")
URL = re.compile(r"(?:https?|ftp)://[!-~]+")
HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)?/?>")
# 独占行首、到行尾都没闭合的标签，如 <img src="a" 后面换行写属性
OPEN_TAG_LINE = re.compile(r"^\s*<[A-Za-z][A-Za-z0-9:-]*(?:\s(?:[^<>\"']|\"[^\"]*\"|'[^']*')*)?$")
# 反斜杠转义：渲染后只剩被转义的字符。* 和 _ 保持原样，免得造出加粗
ESCAPE = re.compile(r"\\([!-)+-/:-@\[-^`{-~])")

# 能跨行的行内结构：开头、结尾、名称
OPENERS = [
    ("<!--", "-->", "HTML 注释"),
    ("{{<", ">}}", "shortcode"),
    ("{{%", "%}}", "shortcode"),
]


def remove_urls(s):
    """去掉裸 URL。结尾的句读和多出来的右括号多半属于句子，留下。"""
    out = []
    pos = 0
    for m in URL.finditer(s):
        url = m.group(0)
        while url:
            last = url[-1]
            if last in ".,:;!?*'\"":
                url = url[:-1]
            elif last == ")" and url.count("(") < url.count(")"):
                url = url[:-1]
            else:
                break
        out.append(s[pos:m.start()])
        pos = m.start() + len(url)
    out.append(s[pos:])
    return "".join(out)


def clean_inline(s):
    """返回三项：清理后的文本、行内代码原文列表、跨行未闭合的结构。

    跨行未闭合的结构由结尾标记和名称组成，没有时为 None。
    """
    codes = []

    def keep_code(m):
        codes.append(m.group(0))
        return CODE_MARK

    s = CODE_SPAN.sub(keep_code, s)
    s = COMMENT.sub(EDGE_MARK, s)
    s = SHORTCODE.sub(EDGE_MARK, s)
    pending = None
    cut = None
    for op, cl, name in OPENERS:
        j = s.find(op)
        if j >= 0 and (cut is None or j < cut[0]):
            cut = (j, cl, name)
    if cut:
        pending = (cut[1], cut[2])
        s = s[:cut[0]] + EDGE_MARK
    s = IMAGE.sub(EDGE_MARK, s)
    s = LINK.sub(lambda m: EDGE_MARK + m.group(1) + EDGE_MARK, s)
    s = REF_LINK.sub(lambda m: EDGE_MARK + m.group(1) + EDGE_MARK, s)
    s = AUTOLINK.sub(EDGE_MARK, s)
    s = remove_urls(s)
    s = HTML_TAG.sub(EDGE_MARK, s)
    if pending is None and OPEN_TAG_LINE.match(s):
        pending = (">", "HTML 标签")
        s = EDGE_MARK
    s = ESCAPE.sub(r"\1", s)
    return s, codes, pending


BQ_PREFIX = re.compile(r"^ {0,3}>(?:[ \t]?(?: {0,3}>)?)*[ \t]?")
LIST_MARKER = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?")
HEADING_MARKER = re.compile(r"^[ \t]*#{1,6}[ \t]+")
FOOTNOTE_DEF = re.compile(r"^[ \t]*\[\^[^\]]+\]:[ \t]*")


def strip_markers(s):
    """去掉行首的引用、列表、标题和脚注定义标记，只留正文。"""
    s = BQ_PREFIX.sub("", s)
    s = LIST_MARKER.sub("", s)
    s = HEADING_MARKER.sub("", s)
    s = FOOTNOTE_DEF.sub("", s)
    return s


Seg = namedtuple("Seg", "no source md_full marked flat fmap codes count_text")


def flatten(md):
    """去掉占位符、* 和 ~~，返回文本和其中每个字符在原文本里的位置。"""
    chars = []
    fmap = []
    i = 0
    n = len(md)
    while i < n:
        c = md[i]
        if c in (CODE_MARK, EDGE_MARK, "*"):
            i += 1
            continue
        if c == "~" and md.startswith("~~", i):
            i += 2
            continue
        chars.append(c)
        fmap.append(i)
        i += 1
    fmap.append(n)
    return "".join(chars), fmap


def make_seg(no, source, md_full, codes, strip):
    md = strip_markers(md_full) if strip else md_full
    flat, fmap = flatten(md)
    count_text = md_full.replace(CODE_MARK, "").replace(EDGE_MARK, "")
    return Seg(no, source, md_full, md, flat, fmap, codes, count_text)


# ---------------------------------------------------------------------------
# 硬命中规则。每条规则返回命中在 seg.flat（或 seg.marked）里的区间。

def flat_rule(pattern, need_han=False):
    pat = re.compile(pattern)

    def find(seg):
        if need_han and not HAS_HAN.search(seg.flat):
            return []
        return [m.span() for m in pat.finditer(seg.flat)]

    return find


# 紧跟在英文字母或数字后面、里面不含汉字的括号，是 foo(x) 这类调用写法
CALL_PARENS = re.compile(rf"(?<=[A-Za-z0-9_])\([^()\n{HAN}]*\)")
HALF_PUNCT = re.compile(rf"{H}[ \t]?[,:;?!()]|[,:;?!()][ \t]?{H}")


def find_half_punct(seg):
    text = CALL_PARENS.sub(lambda m: "\0" * len(m.group(0)), seg.flat)
    return [m.span() for m in HALF_PUNCT.finditer(text)]


def find_ascii_dquote(seg):
    if '"' not in seg.flat or not HAS_HAN.search(seg.flat):
        return []
    return [m.span() for m in re.finditer('"', seg.flat)]


QUOTED = re.compile(r"“[^“”\n]*”")


def _is_han(c):
    return bool(c) and bool(HAS_HAN.match(c))


def _template_dots(text):
    """“只有…才…”这类模板占位里的单个 … 的位置。

    条件：在中文引号里，引号内至少有一个两侧都是汉字的 …；
    其余单个 … 两侧是汉字或引号本身（如结尾的“才…”）。
    """
    exempt = set()
    for m in QUOTED.finditer(text):
        a, b = m.span()
        dots = [d.start() for d in re.finditer("…+", text[a:b]) if len(d.group(0)) == 1]
        dots = [a + d for d in dots]
        if not any(_is_han(text[i - 1]) and _is_han(text[i + 1]) for i in dots):
            continue
        for i in dots:
            left, right = text[i - 1], text[i + 1]
            if (_is_han(left) or left == "“") and (_is_han(right) or right == "”"):
                exempt.add(i)
    return exempt


def find_lone_ellipsis(seg):
    text = seg.flat
    exempt = _template_dots(text)
    out = []
    for m in re.finditer("…+", text):
        if len(m.group(0)) % 2 == 0 or m.start() in exempt:
            continue
        out.append(m.span())
    return out


def find_single_dash(seg):
    return [m.span() for m in re.finditer("—+", seg.flat) if len(m.group(0)) % 2 == 1]


QUANT = ("小时|分钟|秒钟|毫秒|星期|季度|公里|千米|公斤|英寸|厘米|毫米|美元|"
         "个|位|名|人|次|回|遍|轮|趟|天|日|周|月|年|秒|分|倍|页|行|条|项|章|节|段|"
         "步|层|级|张|篇|本|份|套|组|件|台|种|类|处|字|句|元|块|万|千|百|亿|号|期|"
         "届|岁|米|克|斤|度|成|点|题|道|座|家|间|颗|枚|根|只|辆|部|首|幅|门|批|笔|"
         "单|格|帧|核")
NUM_RANGE = (rf"(?<![0-9A-Za-z_.\-/:])\d+(?:\.\d+)?[ \t]?-[ \t]?\d+(?:\.\d+)?"
             rf"(?![0-9.\-/:])[ \t]?(?:{QUANT})")

_NUM = "[0-9０-９.一二两三四五六七八九十百千万]+"
TIMES = (rf"(?:降低?|下降|减少|减小|缩小|缩短|缩减)了?[ \t]?{_NUM}[ \t]?倍"
         rf"|少了[ \t]?{_NUM}[ \t]?倍")

BOLD = re.compile(r"\*\*(?=[^\s*])(.+?)(?<=[^\s*])\*\*")


def _is_punct(c):
    if c in (CODE_MARK, EDGE_MARK):
        return True
    return unicodedata.category(c)[0] in "PS"


def find_bold_punct(seg):
    """CommonMark 的定界规则：加粗内侧贴着标点、外侧紧跟文字时，** 不生效。"""
    md = seg.marked
    out = []
    for m in BOLD.finditer(md):
        inner = m.group(1)
        before = md[m.start() - 1] if m.start() > 0 else ""
        after = md[m.end()] if m.end() < len(md) else ""
        bad_close = (_is_punct(inner[-1]) and after
                     and not after.isspace() and not _is_punct(after))
        bad_open = (_is_punct(inner[0]) and before
                    and not before.isspace() and not _is_punct(before))
        if bad_close or bad_open:
            out.append(("md",) + m.span())
    return out


EMOJI = ("[\U0001F000-\U0001FAFF\u2300-\u23FF\u25A0-\u25FF\u2600-\u27BF\u2B00-\u2BFF]\uFE0F?"
         "|[^\\s]\uFE0F|\uFE0F")

RULES = [
    ("汉字旁的半角标点", find_half_punct),
    ("句末半角句号", flat_rule(rf"{H}\.(?=[ \t]|$)")),
    ("ASCII 双引号", find_ascii_dquote),
    ("汉字旁的 ASCII 单引号", flat_rule(rf"{H}'|'{H}")),
    ("直角引号", flat_rule(r"[「」『』]")),
    ("三点省略号", flat_rule(r"\.{3,}", need_han=True)),
    ("落单的省略号", find_lone_ellipsis),
    ("带空格的破折号", flat_rule("[ \t\u3000]——|——[ \t\u3000]")),
    ("单个破折号", find_single_dash),
    ("en dash", flat_rule("–+")),
    ("汉字间的连字符", flat_rule(rf"{H}[ \t]+-[ \t]+{H}|{H}[ \t]*--[ \t]*{H}")),
    ("ASCII 箭头", flat_rule(r"->|=>")),
    ("正文箭头和逻辑符号", flat_rule("[→←⇒⇐↔⇔∧∨]")),
    ("表情符号", flat_rule(EMOJI)),
    ("顿号叠“以及”", flat_rule(r"、[ \t]*以及")),
    ("数字范围用连字符", flat_rule(NUM_RANGE)),
    ("加粗贴着标点不渲染", find_bold_punct),
    ("倍数病句", flat_rule(TIMES)),
    ("全角数字和字母", flat_rule("[０-９Ａ-Ｚａ-ｚ]")),
]
RULE_ORDER = {name: i for i, (name, _) in enumerate(RULES)}


def to_md_span(seg, span):
    if span[0] == "md":
        return span[1], span[2]
    s, e = span
    ms = seg.fmap[s] if s < len(seg.fmap) else len(seg.marked)
    me = seg.fmap[e - 1] + 1 if e > s else ms
    return ms, me


def snippet(seg, s, e, width=20):
    md = seg.marked
    a = max(0, s - width)
    b = min(len(md), e + width)
    k = md.count(CODE_MARK, 0, a)
    parts = []
    for c in md[a:b]:
        if c == CODE_MARK:
            parts.append(seg.codes[k] if k < len(seg.codes) else "`…`")
            k += 1
        elif c != EDGE_MARK:
            parts.append(c)
    text = "".join(parts).strip()
    return ("……" if a > 0 else "") + text + ("……" if b < len(md) else "")


# ---------------------------------------------------------------------------
# front matter

class FrontMatterError(Exception):
    pass


TOML_KEY = re.compile(r"""^\s*["']?(title|description)["']?\s*=\s*(.*)$""")
YAML_KEY = re.compile(r"""^["']?(title|description)["']?[ \t]*:(?:[ \t]+(.*))?[ \t]*$""")
BLOCK_SCALAR = re.compile(r"^[|>][+-]?[0-9]?[+-]?\s*(?:#.*)?$")
_ESC_SIMPLE = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"',
               "\\": "\\", "/": "/", "0": "\0", "a": "\a", "v": "\v", "e": "\x1b",
               " ": " ", "_": "\u00a0", "N": "\u0085", "L": "\u2028", "P": "\u2029"}
ESC = re.compile(r"\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)")


def decode_backslash(s):
    def rep(m):
        t = m.group(1)
        if len(t) > 1:
            return chr(int(t[1:], 16))
        return _ESC_SIMPLE.get(t, t)

    return ESC.sub(rep, s)


def read_quoted(body, i, text, closer, style, multiline):
    """从 text 开始读引号字符串，返回由行下标和片段组成的列表。片段保留原始转义。"""
    pieces = []
    buf = []
    while True:
        j = 0
        while j < len(text):
            if style == "backslash" and text[j] == "\\" and j + 1 < len(text):
                buf.append(text[j:j + 2])
                j += 2
                continue
            if style == "yaml-single" and text.startswith("''", j):
                buf.append("''")
                j += 2
                continue
            if text.startswith(closer, j):
                pieces.append((i, "".join(buf)))
                return pieces
            buf.append(text[j])
            j += 1
        pieces.append((i, "".join(buf)))
        buf = []
        if not multiline or i + 1 >= len(body):
            return pieces
        i += 1
        text = body[i]


def toml_values(body):
    out = []
    for i, line in enumerate(body):
        if line.lstrip().startswith("["):
            break  # 之后是子表，不再是页面顶层的键
        m = TOML_KEY.match(line)
        if not m:
            continue
        rest = m.group(2).strip()
        if rest.startswith('"""'):
            pieces = read_quoted(body, i, rest[3:], '"""', "backslash", True)
            pieces = [(k, decode_backslash(p.rstrip("\\"))) for k, p in pieces]
        elif rest.startswith("'''"):
            pieces = read_quoted(body, i, rest[3:], "'''", "literal", True)
        elif rest.startswith('"'):
            pieces = read_quoted(body, i, rest[1:], '"', "backslash", False)
            pieces = [(k, decode_backslash(p)) for k, p in pieces]
        elif rest.startswith("'"):
            pieces = read_quoted(body, i, rest[1:], "'", "literal", False)
        else:
            continue
        out.extend((k, p) for k, p in pieces if p.strip())
    return out


def _indented_lines(body, i):
    """返回 key 行之后缩进的续行，每项由行下标和文本组成。"""
    out = []
    k = i + 1
    while k < len(body):
        line = body[k]
        if line.strip() and not line[:1].isspace():
            break
        if line.strip():
            out.append((k, line.strip()))
        k += 1
    return out


def yaml_values(body):
    out = []
    for i, line in enumerate(body):
        m = YAML_KEY.match(line)
        if not m:
            continue
        rest = (m.group(2) or "").strip()
        if rest.startswith('"'):
            pieces = read_quoted(body, i, rest[1:], '"', "backslash", True)
            pieces = [(k, decode_backslash(p).strip()) for k, p in pieces]
        elif rest.startswith("'"):
            pieces = read_quoted(body, i, rest[1:], "'", "yaml-single", True)
            pieces = [(k, p.replace("''", "'").strip()) for k, p in pieces]
        elif not rest or BLOCK_SCALAR.match(rest):
            pieces = _indented_lines(body, i)
        else:
            first = re.sub(r"[ \t]+#.*$", "", rest)
            pieces = [(i, first)] + _indented_lines(body, i)
        out.extend((k, p) for k, p in pieces if p.strip())
    return out


def parse_front_matter(lines):
    """返回正文起始下标，以及由行号和值组成的列表。没有闭合时抛出 FrontMatterError。"""
    if not lines:
        return 0, []
    first = lines[0].rstrip()
    if first == "+++":
        closers, parse = ("+++",), toml_values
    elif first == "---":
        closers, parse = ("---", "..."), yaml_values
    else:
        return 0, []
    for j in range(1, len(lines)):
        if lines[j].rstrip() in closers:
            break
    else:
        raise FrontMatterError(first)
    values = [(k + 2, text) for k, text in parse(lines[1:j])]
    return j + 1, values


# ---------------------------------------------------------------------------
# 正文逐行扫描

FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
BQ_LINE = re.compile(r"^ {0,3}>")
LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
ATX = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
REF_DEF = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*\S")
THEMATIC = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
TABLE_DELIM = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
RAW_HTML_OPEN = re.compile(r"^ {0,3}<(pre|script|style|textarea)(?=[\s>]|$)", re.I)
HIGHLIGHT_OPEN = re.compile(r"^[ \t]*\{\{[<%][ \t]*highlight\b")
HIGHLIGHT_CLOSE = re.compile(r"\{\{[<%][ \t]*/highlight[ \t]*[>%]\}\}")
LABEL_ITEM = re.compile(
    r"^[ \t]*(?:>[ \t]?)*(?:[-*+]|\d{1,9}[.)])[ \t]+"
    r"(?:\*\*[^*\n]+?\*\*[ \t]*[：:]|\*\*[^*\n]+?[：:]\*\*)")


def is_table_delim(s):
    return "|" in s and bool(TABLE_DELIM.match(s))


def split_cells(row):
    s = row.strip()
    parts = re.split(r"(?<!\\)\|", s)
    if s.startswith("|"):
        parts = parts[1:]
    if s.endswith("|") and not s.endswith("\\|") and parts:
        parts = parts[:-1]
    return [p.replace("\\|", "|") for p in parts]


def strip_bq(line):
    return BQ_PREFIX.sub("", line) if BQ_LINE.match(line) else line


def scan_body(lines, start):
    """返回片段列表、结构问题列表和节间分隔线数。"""
    segs = []
    problems = []  # 每项：行号、名称、原文
    thematic = 0
    fence = None      # 围栏符号、个数、行号、是否在引用里、原文
    raw_block = None  # 结尾正则、行号、名称、原文
    pending = None    # 结尾标记、名称、行号、原文
    indented = False
    in_list = False
    in_table = False
    prev_blank = True
    prev_atx = False

    def text_line(no, text, block):
        md_full, codes, pend = clean_inline(text)
        segs.append(make_seg(no, "正文", md_full, codes, block))
        return pend

    n = len(lines)
    for idx in range(start, n):
        line = lines[idx]
        no = idx + 1

        if fence:
            ch, cnt, _, in_bq, _ = fence
            if in_bq and not BQ_LINE.match(line):
                fence = None  # 引用结束，围栏随之结束
            else:
                body = strip_bq(line) if in_bq else line
                if re.match(rf"^[ \t]*{re.escape(ch)}{{{cnt},}}[ \t]*$", body):
                    fence = None
                    prev_blank = False
                    prev_atx = False
                continue

        if raw_block:
            if raw_block[0].search(line):
                raw_block = None
            prev_blank = False
            continue

        if pending:
            j = line.find(pending[0])
            if j < 0:
                continue
            rest = line[j + len(pending[0]):]
            pending = None
            if rest.strip():
                p = text_line(no, rest, False)
                if p:
                    pending = p + (no, line.strip())
            prev_blank = False
            continue

        if not line.strip():
            prev_blank = True
            in_table = False
            continue

        in_bq = bool(BQ_LINE.match(line))
        content = strip_bq(line)
        expanded = content.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(" "))

        # 缩进式代码块：上一行为空、不在列表里、缩进至少四格
        if not in_bq:
            if indented:
                if indent >= 4:
                    continue
                indented = False
            elif indent >= 4 and prev_blank and not in_list:
                indented = True
                continue

        if LIST_ITEM.match(content):
            in_list = True
        elif indent == 0 and (prev_blank or ATX.match(content) or FENCE_OPEN.match(content)):
            in_list = False

        m = FENCE_OPEN.match(content)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = (m.group(1)[0], len(m.group(1)), no, in_bq, line.strip())
            prev_blank = False
            continue

        if HIGHLIGHT_OPEN.match(content):
            if not HIGHLIGHT_CLOSE.search(content):
                raw_block = (HIGHLIGHT_CLOSE, no, "highlight shortcode", line.strip())
            prev_blank = False
            continue

        m = RAW_HTML_OPEN.match(content)
        if m:
            closer = re.compile(rf"</{m.group(1)}\s*>", re.I)
            if not closer.search(content, m.end()):
                raw_block = (closer, no, f"<{m.group(1).lower()}> 块", line.strip())
            prev_blank = False
            continue

        if is_table_delim(content):
            in_table = True
            prev_blank = False
            continue

        tm = THEMATIC.match(content)
        if tm:
            # --- 紧跟段落时是 setext 标题的下划线，不算分隔线
            if tm.group(1) != "-" or prev_blank or prev_atx:
                thematic += 1
            prev_blank = False
            prev_atx = False
            in_table = False
            continue

        if REF_DEF.match(content):
            prev_blank = False
            continue

        nxt = strip_bq(lines[idx + 1]) if idx + 1 < n else ""
        if "|" in content and (in_table or is_table_delim(nxt)
                               or content.lstrip().startswith("|")):
            in_table = True
            for cell in split_cells(content):
                md_full, codes, _ = clean_inline(cell)
                segs.append(make_seg(no, "表格", md_full, codes, False))
            prev_blank = False
            prev_atx = False
            continue
        in_table = False

        p = text_line(no, content, True)
        if p:
            pending = p + (no, line.strip())
        prev_blank = False
        prev_atx = bool(ATX.match(content))

    if fence:
        problems.append((fence[2], "围栏代码块没有闭合", fence[4]))
    if raw_block:
        problems.append((raw_block[1], f"{raw_block[2]}没有闭合", raw_block[3]))
    if pending:
        problems.append((pending[2], f"{pending[1]}没有闭合", pending[3]))
    return segs, problems, thematic


# ---------------------------------------------------------------------------
# 计数

AI_WORDS = ["此外", "然而", "值得注意的是", "总而言之", "综上所述", "至关重要", "深入探讨",
            "赋能", "助力", "宝贵的", "关键性的", "不可或缺", "强有力", "旨在", "致力于"]
NEG_PATTERNS = [
    ("这不是……而是", re.compile(r"这不是[^。！？\n]*?而是")),
    ("不仅仅是", re.compile("不仅仅是")),
    ("恰恰相反", re.compile("恰恰相反")),
]
BOLD_COUNT = re.compile(r"\*\*(?=[^\s*])[^\n]+?(?<=[^\s*])\*\*")


def count_all(segs, thematic):
    texts = [s.count_text for s in segs]
    han = sum(len(HAS_HAN.findall(t)) for t in texts)

    def total(pat):
        return sum(len(pat.findall(t)) for t in texts)

    def breakdown(items):
        found = [(label, total(p)) for label, p in items]
        return sum(c for _, c in found), [(label, c) for label, c in found if c]

    rows = [
        ("加粗片段", sum(len(BOLD_COUNT.findall(s.md_full)) for s in segs), "", []),
        ("标签式列表项",
         sum(1 for s in segs if s.source == "正文" and LABEL_ITEM.match(s.md_full)), "", []),
        ("节间分隔线", thematic, "", []),
        ("破折号 ——", total(re.compile("——")), " 对", []),
        ("“被”", total(re.compile("被")), "", []),
    ]
    c, parts = breakdown([(w, re.compile(w)) for w in ("进行", "作出")])
    rows.append(("“进行”“作出”", c, "", parts))
    c, parts = breakdown([(w, re.compile(w)) for w in AI_WORDS])
    rows.append(("AI 高频词", c, "", parts))
    c, parts = breakdown(NEG_PATTERNS)
    rows.append(("否定式排比线索", c, "", parts))
    return han, rows


# ---------------------------------------------------------------------------
# 汇总输出

def check_text(text):
    """返回硬命中列表、汉字数和计数行。

    每条硬命中依次是行号、规则序、规则名、来源、次数、片段。
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    start, fm_values = parse_front_matter(lines)
    segs = []
    for no, value in fm_values:
        md_full, codes, _ = clean_inline(value)
        segs.append(make_seg(no, "front matter", md_full, codes, False))
    body_segs, problems, thematic = scan_body(lines, start)
    segs.extend(body_segs)

    found = {}
    for seg in segs:
        for name, find in RULES:
            spans = find(seg)
            if not spans:
                continue
            key = (seg.no, RULE_ORDER[name], name, seg.source)
            if key in found:
                found[key][0] += len(spans)
            else:
                s, e = to_md_span(seg, spans[0])
                found[key] = [len(spans), snippet(seg, s, e)]
    hits = [k + tuple(v) for k, v in found.items()]
    for no, name, raw in problems:
        hits.append((no, len(RULES), name, "正文", 1, raw[:60]))
    hits.sort(key=lambda h: (h[0], h[1]))
    han, rows = count_all(segs, thematic)
    return hits, han, rows


def format_hit(hit):
    no, _, name, source, times, snip = hit
    notes = []
    if source != "正文":
        notes.append(source)
    if times > 1:
        notes.append(f"共 {times} 处")
    tag = f"（{'，'.join(notes)}）" if notes else ""
    return f"  【{name}】第 {no} 行{tag}：{snip}"


def format_count(name, c, unit, parts, han):
    extra = []
    if han:
        extra.append(f"每千字 {c * 1000 / han:.1f}")
    if parts:
        extra.append("，".join(f"{label} {k}" for label, k in parts))
    tail = f"（{'；'.join(extra)}）" if extra else ""
    return f"  {name}：{c}{unit}{tail}"


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    bad = False
    for path in argv[1:]:
        print(f"===== {path} =====")
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print("错误：文件不是 UTF-8 编码，未检查。")
            bad = True
            continue
        except OSError as e:
            print(f"错误：读取失败（{e.strerror or e}），未检查。")
            bad = True
            continue
        try:
            hits, han, rows = check_text(text)
        except FrontMatterError as e:
            print(f"错误：front matter 没有闭合。第 1 行以 {e} 开头，"
                  f"直到文件末尾都没有对应的 {e}，本文件未做其余检查。")
            bad = True
            continue
        if hits:
            bad = True
            print(f"硬命中（{len(hits)} 条）：")
            for hit in hits:
                print(format_hit(hit))
        else:
            print("硬命中：无")
        print("计数：")
        print(f"  汉字总数：{han}")
        for name, c, unit, parts in rows:
            print(format_count(name, c, unit, parts, han))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
