# Zotero Literature Radar

Zotero Literature Radar 是一个 Codex skill，用于围绕用户自定义的研究主题，持续收集和筛选 Zotero RSS/feed 中的最新论文与前沿研究，适合结合codex自动化任务使用。它会读取最近进入 Zotero 订阅源的条目，根据可配置的主题策略打分分档，生成 Markdown 文献雷达周报，并可在用户确认后把精选论文导入 Zotero collection。

它适合作为固定运行的科研信息雷达：在 Zotero 中维护期刊 RSS 订阅，在工作区主题文件中描述你的研究兴趣，然后让 Codex 定期生成“下一批最值得读什么”的聚焦报告。

## 功能

- 从 Zotero RSS/feed 条目生成 Markdown 文献雷达报告。
- 按研究主题筛选最新论文和相关前沿研究。
- 支持 A/B/C 分档、精度门控、关键词、忽略规则和展示数量配置。
- 用本地推荐缓存优先展示新的 Top 3 和 A 档论文，减少重复推荐。
- 根据导入缓存和只读复核结果展示论文当前 Zotero 导入状态。
- 所有 Zotero 写入流程都先 dry-run，再由用户确认执行。
- 支持将 Top3、A 档或 Top3+A 档论文导入指定 Zotero collection。
- 运行时缓存保存在报告输出目录中。

## 运行要求

- Codex 桌面端，或其他支持本地 skills 的 Codex 环境。
- Zotero 桌面端，并配置 RSS/feed 订阅。
- Python 3.10 或更新版本，推荐 Python 3.11+。
- 导入或更新 Zotero 条目时，需要 Zotero Web API 环境变量。
- 仅生成周报不需要 Zotero Web API key。

## 安装

将本仓库复制到 Codex skills 目录：

```text
~/.codex/skills/zotero-literature-radar
```

Windows 上通常是：

```text
%USERPROFILE%\.codex\skills\zotero-literature-radar
```

确保 `SKILL.md` 位于 skill 目录根部。

## 配置 Zotero 读取

报告生成脚本会自动查找常见的 Zotero SQLite 路径：

```text
%USERPROFILE%\Zotero\zotero.sqlite
~/Zotero/zotero.sqlite
%APPDATA%\Zotero\zotero.sqlite
```

也可以通过环境变量指定：

```text
ZOTERO_DB_PATH=/path/to/zotero.sqlite
```

或者在工作区主题文件中设置 `zotero_sqlite`。

## 配置 Zotero 写入

只有导入、恢复、更新 Zotero 条目时才需要 Zotero Web API 凭据。仅生成周报不需要配置这一部分。

### 1. 创建 Zotero API Key

1. 打开 Zotero API Keys 页面：
   <https://www.zotero.org/settings/keys>
2. 点击 `Create new private key`。
3. 至少勾选：
   - `Allow library access`
   - 需要写入个人库时，给 `Default Group Permissions` 或个人库权限开启读写。
   - 需要写入 group library 时，给目标 group 开启读写。
4. 创建后复制生成的 key。关闭页面后通常无法再次看到完整 key。

### 2. 确认 Library ID 和 Library Type

个人库：

- `ZOTERO_LIBRARY_TYPE=user`
- `ZOTERO_LIBRARY_ID` 使用你的 Zotero user ID。
- user ID 可以在 Zotero Web API key 页面、Zotero 网站个人资料或 API 文档提示中找到。

群组库：

- `ZOTERO_LIBRARY_TYPE=group`
- `ZOTERO_LIBRARY_ID` 使用 group ID。
- group ID 通常可以从群组页面 URL 中看到，例如 `https://www.zotero.org/groups/1234567/group-name` 中的 `1234567`。

### 3. 在 Windows PowerShell 中配置

写入当前 Windows 用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable("ZOTERO_API_KEY", "your_zotero_api_key", "User")
[Environment]::SetEnvironmentVariable("ZOTERO_LIBRARY_ID", "your_library_id", "User")
[Environment]::SetEnvironmentVariable("ZOTERO_LIBRARY_TYPE", "user", "User")
```

写入后请重启 Codex、PowerShell 或终端，让新环境变量生效。

如果使用 group library：

```powershell
[Environment]::SetEnvironmentVariable("ZOTERO_LIBRARY_TYPE", "group", "User")
```

### 4. 在 Windows CMD 中配置

写入当前 Windows 用户环境变量：

```bat
setx ZOTERO_API_KEY "your_zotero_api_key"
setx ZOTERO_LIBRARY_ID "your_library_id"
setx ZOTERO_LIBRARY_TYPE "user"
```

`setx` 写入后只对新打开的终端生效。

### 5. 在 macOS/Linux 中配置

临时配置：

```bash
export ZOTERO_API_KEY="your_zotero_api_key"
export ZOTERO_LIBRARY_ID="your_library_id"
export ZOTERO_LIBRARY_TYPE="user"
```

永久配置可以加入 `~/.zshrc`、`~/.bashrc` 或你的 shell 配置文件：

```bash
export ZOTERO_API_KEY="your_zotero_api_key"
export ZOTERO_LIBRARY_ID="your_library_id"
export ZOTERO_LIBRARY_TYPE="user"
```

### 6. 验证环境变量

PowerShell：

```powershell
echo $env:ZOTERO_LIBRARY_ID
echo $env:ZOTERO_LIBRARY_TYPE
```

不要在截图、公开 issue 或 README 中打印完整 `ZOTERO_API_KEY`。

不要把 API key 写入 Obsidian 笔记、Git 仓库或 skill 文件。

## 工作区主题配置

每个工作区可以有自己的主题文件：

```text
.codex/zotero-literature-radar/research-theme.md
```

如果该文件不存在，skill 会从 `templates/research-theme.md` 初始化一份。

主题文件中包含一个 JSON 配置块，常用字段包括：

- `lookback_days`：RSS/feed 检索窗口，单位为天。
- `output_dir`：报告输出目录；相对路径会解析到当前工作区下。
- `max_items_per_tier`：A/B/C 各档展示数量上限。
- `ignore_title_patterns`：用于忽略非论文条目的标题正则。
- `ignore_topic_patterns`：用于排除无关主题的正则。
- `topics`：主题评分规则，包含 `tier`、`weight`、`required_any` 和 `keywords`。

示例主题见 `examples/` 目录。

## 生成周报

在 Codex 中输入：

```text
使用 $zotero-literature-radar 生成与我的研究主题相关的最新论文周报。
```

默认报告路径：

```text
<output_dir>/Zotero论文订阅周报-YYYY-MM-DD.md
```

如果当天已经生成过报告，会自动编号，避免覆盖：

```text
Zotero论文订阅周报-YYYY-MM-DD-02.md
Zotero论文订阅周报-YYYY-MM-DD-03.md
```

运行时状态保存在：

```text
<output_dir>/.zotero-literature-radar/
```

该目录用于缓存推荐和导入状态，不建议作为普通笔记目录维护。

## 导入论文到 Zotero

导入流程分两步：先 dry-run，确认后再写入 Zotero。

示例请求：

```text
使用 $zotero-literature-radar 将这份报告中的 Top3 论文 dry-run 导入 Codex_Filter_Database/99_To_Read。
```

检查 dry-run 清单后，再让 Codex 执行写入。

导入流程可以：

- 解析目标 collection。
- 检测已存在的活动条目。
- 检测 deleted/trash 冲突。
- 创建新的 `journalArticle` 条目。
- 在用户确认后恢复 deleted/trash 条目。
- 添加标签和 collection 归属。
- 只把中文题名写入 `Extra` 的 `titleTranslation: ...`。
- 写入后读回验证，成功后再更新 `imported-items.json`。

## 与 Obsidian 联合使用

建议将 Codex 工作区设置为 Obsidian vault 根目录。

推荐目录结构：

```text
your-vault/
  .codex/zotero-literature-radar/research-theme.md
  Literature Radar Reports/
  Reading Notes/
```

中文 vault 中也可以使用：

```text
论文追踪周报/
论文阅读报告/
```

推荐工作流：

- 将每周报告生成到专门的周报目录。
- 直接在 Obsidian 中阅读、搜索和链接周报。
- 对 Top3 或 A 档论文建立单独精读笔记。
- 筛选理由保留在 Markdown 周报中，不写入 Zotero 条目元数据。
- `.zotero-literature-radar/` 是运行时缓存目录，不建议当作笔记目录。

可选的报告笔记 frontmatter：

```yaml
---
type: literature-radar
source: zotero-rss
date: 2026-01-01
tags:
  - zotero
  - literature-radar
---
```

如果将 Obsidian vault 同步到 GitHub，请忽略生成周报、运行时缓存、导入计划、API key 和私人笔记，除非你确实想公开它们。

## 自动化提示词

每周自动化可以使用类似提示词：

```text
使用 $zotero-literature-radar 生成与我的研究主题相关的最新论文周报。完成后简短汇报生成的 Markdown 路径、原始条目数、入选条目数、A/B/C 总数、A/B/C 展示数量，以及本周最值得精读的 3 篇论文标题。
```

建议把 Zotero 导入作为单独确认流程，不要默认在周报自动化中直接写入 Zotero。

## 安全说明

- 本地 Zotero SQLite 只读使用。
- Zotero 写入使用环境变量中的 Web API 凭据。
- 每次 Zotero 写入前必须先生成 dry-run 清单。
- deleted/trash 命中默认视为冲突，需要用户确认。
- 导入缓存只记录历史状态；周报生成时会只读复核当前 Zotero 状态。
- 生成周报不会下载 PDF，也不会写入 Zotero。
