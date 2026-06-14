# Expression Spark

Expression Spark 是一个面向短视频创作者的 Agent Skill。

它不会在用户脑子空白时立刻代写文案，而是通过低压力、一次一问的访谈，把用户已有的经历、业务判断和感悟沉淀为：

- 经用户确认的真实原话
- 可继续发展的轻量选题卡
- 带证据和状态的个人画像
- 证据充分后生成的本人 Persona Skill

## 核心原则

- 先让用户愿意说，再判断内容价值。
- 每次只问一个问题。
- 未经用户确认，不保存长期语料。
- 不保存完整聊天记录。
- 原话不润色，画像不覆盖矛盾证据。
- 不编造用户经历、客户案例或立场。

## 安装

### 从 GitHub 克隆

将整个仓库放入 Agent 的 Skills 目录：

```bash
git clone https://github.com/zxc779177631-ui/expression-spark.git \
  ~/.agents/skills/expression-spark
```

不同运行时的常见目录：

| Runtime | 安装路径 |
|---|---|
| Codex / 通用 Agent | `~/.agents/skills/expression-spark/` |
| Claude Code | `~/.claude/skills/expression-spark/` |
| 项目级 Skill | `<project>/.agents/skills/expression-spark/` |

安装后重新启动 Agent，或开启一个新会话，让运行时重新扫描 Skills。

### 使用 `.skill` 安装包

从仓库的 [`packages/expression-spark.skill`](packages/expression-spark.skill) 下载，再使用运行时提供的 Skill 导入能力安装。

## 如何触发

不需要记住固定命令，直接说真实需求：

```text
我想做短视频，但每次要拍的时候脑子一片空白，你跟我聊聊。
```

```text
最近发生了不少事，帮我把里面值得表达的东西聊出来。
```

```text
帮我收集个人语料，慢慢建立我的表达风格。
```

```text
看看我还有哪些没拍过的选题。
```

```text
我积累的语料够不够蒸馏一个我的 Persona Skill？
```

以下场景不应触发 Expression Spark：

```text
主题已经定了，直接帮我写一条 60 秒口播稿。
```

## 首次使用

首次会话会：

1. 询问称呼、当前业务和常聊领域。
2. 默认从低压力采访开始，Agent 根据表达状态适配；用户也可以明确指定模式。
3. 告知资产存储位置和隐私规则。
4. 创建个人表达资产库。

三种采访模式：

- `deep-interviewer`：好奇的深度访谈者
- `gentle-journal`：低压力日记搭子
- `content-coach`：帮助识别内容张力的内容教练

输入以文字为主。使用豆包输入法、微信输入法或 Typeless 口述输入，更容易保留真实口播习惯。

## 资产存储

检测到 Obsidian 时，默认使用：

```text
表达资产/<user-slug>/
```

没有 Obsidian 时，默认使用：

```text
~/expression-library/<user-slug>/
```

资产目录包含：

```text
config.md
sessions/YYYY/MM/<session-id>.md
topics/<topic-id>.md
signals/<signal-id>.md
profile/current.md
state.json
generated/<user-slug>-persona/
```

## CLI

`scripts/library.py` 使用 Python 标准库，无额外 Python 依赖。

```bash
python3 scripts/library.py --help
```

主要命令：

```bash
# 初始化资产库
python3 scripts/library.py init --user-slug jia-run --name 嘉润

# 登记用户已确认的会话资产
python3 scripts/library.py register --library "<资产库路径>" --payload payload.json

# 查看声纹预览与 Persona 准备度
python3 scripts/library.py status --library "<资产库路径>"

# 为下游写稿生成有证据的上下文包
python3 scripts/library.py context --library "<资产库路径>" --query "客户选择"

# 检查证据引用与状态一致性
python3 scripts/library.py validate --library "<资产库路径>"

# 导出默认不含语料正文的试用成果快照
python3 scripts/library.py feedback --library "<资产库路径>" --output outcomes.md

# 先预览遗忘影响，确认后再应用
python3 scripts/library.py forget --library "<资产库路径>" --contains "前合伙人" --dry-run
```

## 测试

```bash
python3 -m unittest discover -s tests -v
```

当前测试覆盖：

- 用户确认门禁
- 原话逐字保存
- 不保存完整聊天记录
- 默认模式切换
- 重复画像证据门槛
- Persona 准备度
- 确认画像防静默改写
- 遗忘影响预览与派生画像重建

## 项目结构

```text
expression-spark/
├── SKILL.md
├── README.md
├── assets/
├── evals/
├── references/
├── scripts/library.py
└── tests/test_library.py
```
