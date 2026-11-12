# speak-like-chinese

A Claude Code skill that keeps Chinese output idiomatic: no translationese, no AI-style prose.

让 Claude Code 写出来的中文像中国人写的。它管两类问题：翻译腔（硬译、生硬搭配、欧化句式、比喻直译、自造术语）和 AI 腔（套话、金句、标签式列表、凑数的排比）。规则会随着使用增补，新发现的问题下次就能用上。

## 怎么用

安装到用户级 skill 目录，所有项目共用：

```sh
git clone https://github.com/wangzw/speak-like-chinese.git ~/.claude/skills/speak-like-chinese
git -C ~/.claude/skills/speak-like-chinese config core.hooksPath scripts/githooks
```

在 `~/.claude/CLAUDE.md` 里加两行，第一行把常驻规则导入每个会话，第二行告诉 Claude 什么时候调用这个 skill：

```markdown
- 中文常驻规则：@~/.claude/skills/speak-like-chinese/core.md
- 写文档、博客、报告，或审阅别人的中文时，调用 speak-like-chinese skill。
```

之后分两档生效：

- 会话档：所有中文回复都受 `core.md` 的常驻规则约束，不用额外操作。
- 严格档：写文档、博客、报告、调研或几段以上的回复时，Claude 会自动调用 skill，也可以手动输入 `/speak-like-chinese`。流程是写前通读清单，写后跑脚本、人工过清单、把拿不准的地方列出来。

## 目录

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 入口：触发条件、流程、脱敏规则、进化规则 |
| `core.md` | 常驻核心规则，由 CLAUDE.md 导入 |
| `checklist.md` | 严格档自查清单：翻译腔、AI 腔、写后核查、评分 |
| `additions.md` | 增补文件：每次新增模式的登记表 |
| `references/error-corpus.md` | 错例库：从真实会话里审出来的 7047 条错例，按类别整理成一百多个模式，每条有病象、形式、实例、自查 |
| `scripts/zh_check.py` | 机械检查：半角标点、引号、省略号、破折号、箭头、表情、倍数病句等 19 条规则，另给加粗、分隔线、AI 高频词的每千字密度 |
| `scripts/tests/` | 检查脚本的回归样例，改脚本后跑 `sh scripts/tests/run.sh` |
| `scripts/privacy_check.py` | 隐私扫描：邮箱、IP、密钥、提交哈希、内部文件名和内部名称 |
| `scripts/githooks/pre-commit` | 提交前自动跑隐私扫描，命中就拦下 |

## 自我进化

清单不是写死的。用户指出一处中文用法问题，或 Claude 在写后核查时发现清单没覆盖的问题并经用户确认，当轮就一次做完：脱敏、查重、并进清单和常驻规则、把例句存进错例库第十节、在增补文件里登记一行。只确认一次，没有中间状态。

## 脱敏

这个仓库是公开的，错例库的例句来自真实会话。例句入库前要把项目名、文件名、模块名、提交哈希、人名换成占位，只保留要说明的语言点。`privacy-denylist.txt` 放你自己的内部名称，不进仓库；`privacy-allowlist.txt` 放确认公开的文件名和地址，随仓库发布。提交前钩子会对暂存文件再扫一遍。

## 检查脚本

```sh
python3 -I scripts/zh_check.py 文件.md
python3 -I scripts/privacy_check.py 文件.md
```

两个脚本只用标准库。`zh_check.py` 跳过代码块、行内代码、链接地址和 HTML 标签，表格按单元格检查，front matter 只查标题和描述；有硬命中时退出码为 1。

## 许可

Apache License 2.0，见 `LICENSE`。
