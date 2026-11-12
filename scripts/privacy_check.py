#!/usr/bin/env python3
"""隐私扫描：找出不该进公开仓库的内容。

用法：python3 -I privacy_check.py 文件1 [文件2 …]

检查项：邮箱、IPv4、URL、密钥格式、提交哈希、带扩展名的文件名或路径、
以及 skill 目录下 privacy-denylist.txt（不进仓库）里列出的内部名称。
任一命中退出码为 1。命中的 URL 和文件名需要人工判断是否公开，其余一律处理。
"""
import re
import sys
import pathlib

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
DENYLIST = SKILL_DIR / "privacy-denylist.txt"
ALLOWLIST = SKILL_DIR / "privacy-allowlist.txt"

# skill 自己的文件和通用占位名不算内部文件
ALLOW_BASENAMES = {
    "SKILL.md", "core.md", "checklist.md", "additions.md", "error-corpus.md",
    "README.md", "zh_check.py", "privacy_check.py", "CLAUDE.md", "MEMORY.md",
    "privacy-denylist.txt", "privacy-allowlist.txt", "library.json", "hard-translations.md", "run.sh",
}
ALLOW_STEMS = {"foo", "bar", "baz", "example", "demo", "a", "b", "c", "x", "y"}
# 脱敏时统一使用的占位哈希，不算提交哈希
PLACEHOLDER_HASHES = {"abc1234", "deadbeef", "0000000"}

# RFC 2606 保留的示例域名，测试样例里会用到
EXAMPLE_DOMAIN = re.compile(r"https?://([a-z0-9-]+\.)*example\.(com|org|net)\b")

URL_RE = re.compile(r"https?://[^\s)）>\]`]+")

PATTERNS = [
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("IPv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("URL", re.compile(r"https?://[^\s)）>\]`]+")),
    ("密钥格式", re.compile(r"\b(?:sk-|ghp_|gho_|github_pat_|AKIA|xox[baprs]-|AIza)[A-Za-z0-9_-]{8,}")),
    ("提交哈希", re.compile(r"(?<![A-Za-z0-9])[0-9a-f]{7,40}(?![A-Za-z0-9])")),
]
FILE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])[A-Za-z0-9_./-]*[A-Za-z0-9_-]\."
    r"(?:md|txt|ts|tsx|js|jsx|mjs|go|py|rs|java|kt|rb|php|c|h|cpp|cs|swift|"
    r"yaml|yml|json|toml|ini|env|sh|sql|css|scss|html|vue|svelte|proto)\b"
)


def load_allowlist():
    if not ALLOWLIST.exists():
        return set()
    return {l.strip() for l in ALLOWLIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def load_denylist():
    if not DENYLIST.exists():
        return []
    terms = []
    for line in DENYLIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def is_hash_like(s):
    # 纯数字不算哈希；必须同时含字母和数字
    return any(ch.isdigit() for ch in s) and any(ch.isalpha() for ch in s)


def scan_file(path, deny, allow=frozenset()):
    hits = []
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        return [("读取失败", 0, str(e))]
    for no, line in enumerate(lines, 1):
        for name, pat in PATTERNS:
            for m in pat.finditer(line):
                if name == "提交哈希" and (not is_hash_like(m.group(0)) or m.group(0) in PLACEHOLDER_HASHES):
                    continue
                if name == "URL" and EXAMPLE_DOMAIN.match(m.group(0)):
                    continue
                if m.group(0) in allow:
                    continue
                hits.append((name, no, m.group(0)))
        line_no_url = URL_RE.sub("", line)
        for m in FILE_RE.finditer(line_no_url):
            token = m.group(0)
            base = token.rsplit("/", 1)[-1]
            stem = base.rsplit(".", 1)[0]
            if base in ALLOW_BASENAMES or stem.lower() in ALLOW_STEMS or "foo" in stem.lower():
                continue
            if token in allow or base in allow or token.lstrip("/") in allow:
                continue
            hits.append(("文件名或路径", no, token))
        for term in deny:
            if term in line:
                hits.append(("内部名称", no, term))
    return hits


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    deny = load_denylist()
    allow = load_allowlist()
    bad = False
    for path in argv[1:]:
        hits = scan_file(path, deny, allow)
        print(f"===== {path} =====")
        if not hits:
            print("（无）")
            continue
        bad = True
        for name, no, token in hits:
            print(f"[{name}] {no}: {token}")
    if deny:
        print(f"（已加载 privacy-denylist.txt，{len(deny)} 条内部名称）")
    else:
        print("（未找到 privacy-denylist.txt，只做通用模式扫描）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
