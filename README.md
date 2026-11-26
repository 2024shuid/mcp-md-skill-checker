# MD Skill Checker MCP

专门扫描存放 **Skill 定义**的 Markdown 文件，读取里面的 Skill SOP 做规则校验 + 打分。
**只读、不修改文件**，输出结构化纯文本报告，直接喂给上层 LLM 用来迭代优化 Skill 文档。

- 输入：用户自己在项目 `skills/` 目录下放的一堆 skill 类型 `.md`
- 输出：分数 + 分项得分 + 缺陷清单 + 自然语言修改建议
- 依赖：只依赖官方 `mcp` SDK（内置 FastMCP），不依赖向量库，不需要 uvx

## 目录结构

```
mcp_skill_checker/
├── server.py          # MCP 服务本体（stdio）
├── requirements.txt   # 只有一行依赖：mcp>=1.24,<2
├── chatmcp.yaml       # ChatMCP 客户端配置样例
└── README.md
```

## 三个 Tool（全部只读）

### 1. `check_skill_md`

| 入参 | 类型 | 说明 |
| --- | --- | --- |
| `file_path` | str | Skill 文档路径，绝对路径或相对 `SKILL_DIR` 的路径 |

读取单个 md，执行全套校验，返回总分 + 分项得分 + 缺陷清单 + 修改建议。

```
Skill 质检报告
文件：D:\...\skills\writing.md
总分：70/100（C｜及格）

【技能目标清晰】20/20 ✅ 结构完整
【执行步骤完备】15/25 ⚠️ 步骤里缺少判定条件 / 分支说明
【输入输出契约】12/20 ⚠️ 没有指定输出格式
【异常与兜底】10/15 ⚠️ 缺少兜底 / fallback 策略
【约束与禁止行为】5/10 ❌ 缺少禁止行为描述
【可观测与日志】8/10 ⚠️ 没有标注关键节点

缺失项（4）：
- 步骤里缺少判定条件 / 分支说明
- 没有指定输出格式
- 缺少兜底 / fallback 策略
- 缺少禁止行为描述
优化建议：
1. 在关键步骤写明判定条件与分支（如果…则…否则…）
2. 规定输出格式（JSON / 文本 / 表格）并说明关键字段
...
```

### 2. `scan_skill_dir`

| 入参 | 类型 | 说明 |
| --- | --- | --- |
| `dir_path` | str | 可选。为空时用 `SKILL_DIR`，相对路径按 `SKILL_DIR` 解析 |

递归扫描目录下所有 `.md`（`README / changelog / license` 之类自动忽略），
用标记词识别 Skill 文档（命中 `skill / 技能 / 步骤 / 输入 / 输出 / 适用场景 / 触发条件 / 禁止` 中任意 **2 个及以上**）。
**未命中的文件也不会被隐藏**——照样按规则打分，只标注「疑似非 Skill」，避免写得差的 skill 从报告里消失。
报告**低分排在前面**，方便优先看短板。

```
Skill 库巡检报告
目录：D:\...\skills
扫描 3 个 Markdown

[1] 0/100 D｜待改进 writing.md（疑似非 Skill）
     短板：技能目标清晰 0/20、执行步骤完备 0/25
[2] 82/100 B｜良好 review.md
     短板：可观测与日志 6/10、异常与兜底 11/15
[3] 100/100 A｜优秀 coding.md
     短板：无明显短板

汇总：平均 60.7 分，最高 100 分（coding.md），最低 0 分（writing.md）
优先优化：writing.md
```

### 3. `get_check_criteria`

入参：无。返回整套打分规则原文（维度、权重、每个小项的命中规则）。
LLM 拿到标准后可以自己按规范写新的 skill md，形成「写 → 查 → 改」闭环。

## 评分维度（总分 100）

| 维度 | 分值 | 判定要素 |
| --- | --- | --- |
| 技能目标清晰 | 20 | 解决什么问题(8) / 适用场景(6) / 不适用场景(6) |
| 执行步骤完备 | 25 | 有步骤列表(10) / 步骤 ≥3 条(8) / 有判定与分支(7) |
| 输入输出契约 | 20 | 输入说明(7) / 输出格式(8) / 示例或 schema(5) |
| 异常与兜底 | 15 | 失败与异常(6) / 兜底 fallback(5) / 边界情况(4) |
| 约束与禁止行为 | 10 | 禁止动作(6) / 前置条件与限制(4) |
| 可观测与日志 | 10 | 日志记录(6) / 关键节点(4) |

- 判定方式：关键词 / 结构特征匹配，每个小项独立计分，**不需要重型 LLM 内置在 MCP 里**
- 等级：≥90 A｜优秀，≥75 B｜良好，≥60 C｜及格，<60 D｜待改进
- 标记：小项达成率 ≥90% ✅，≥60% ⚠️，否则 ❌

## 安装

```bash
pip install -r requirements.txt   # 等价于 pip install "mcp>=1.24,<2"
```

> 为什么不是 `fastmcp>=1.0,<2`：`fastmcp` 是社区的早期封装包，而官方 `mcp` SDK 已内置 FastMCP，
> 代码写法完全一样（`FastMCP` + `@mcp.tool`）。本项目所在环境里 `mcp` 被 `langchain-mcp-adapters`
> 锁在 1.x，再多装一层 fastmcp 容易引入新的版本冲突。若你确实想用社区包，把
> `from mcp.server.fastmcp import FastMCP` 改成 `from fastmcp import FastMCP` 即可。

## 启动（stdio，不需要 uvx）

```bash
python server.py
```

stdio 模式下服务通过标准输入输出与客户端通信，**不要往 stdout 打印调试信息**（本服务所有工具只返回字符串）。

## 接入 LangChain / LangGraph

和项目里 `texts/mcp_text.py` 的写法一致，工具会被自动转成 LangChain Tool：

```python
import sys
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
    {
        "skill_checker": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [r"D:\project\pythonProject\AgentTest\mcp_skill_checker\server.py"],
            "env": {"SKILL_DIR": r"D:\project\pythonProject\AgentTest\skills"},
        }
    }
)

tools = await client.get_tools()   # 得到 check_skill_md / scan_skill_dir / get_check_criteria
agent = create_agent(model, tools)
```

典型用法：让 agent 先 `scan_skill_dir` 找出最差的 skill，再 `check_skill_md` 拿详细缺陷，
按「优化建议」改写文档，改完再 `check_skill_md` 复检，形成闭环。

## 接入 ChatMCP

把 `chatmcp.yaml` 里的 `mcpServers` 段合并进 ChatMCP 的配置，**把三处绝对路径改成你本机的**：

| 配置项 | 作用 |
| --- | --- |
| `command` | 装了 `mcp` 包的解释器绝对路径（避免 PATH 里的 python 找不到依赖） |
| `args` | `server.py` 的绝对路径 |
| `env.SKILL_DIR` | skill 文档根目录，相对路径的基准 |

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SKILL_DIR` | `./skills`（相对进程工作目录） | skill 根目录；相对入参都基于它解析 |

## 设计边界

- ❌ **不会自动修改、重写 md**：只检测、打分、给建议；修改动作交给外层 LLM / Agent
- ❌ 不依赖向量库，纯文本关键词规则，轻量；复杂语义判断交给上层大模型
- ❌ 不强制固定 md 模板，用户随便写 skill，容错性强
- ❌ 不写文件、不建缓存、不联网，只有读操作
- ✅ 输出纯文本报告，可直接喂给 LangGraph 里的 Agent，用来迭代优化 Skill 文档

## 已知限制

- 打分是**规范性检查**，不是质量评判：把规则要素写全就能拿高分，但不代表流程本身合理
- Skill 文档识别靠标记词，纯英文或写法极简的文档会被标为「疑似非 Skill」（但依然打分，不会漏报）
- 关键词是中文为主，英文 skill 文档得分会偏低
- 关键词匹配会有误报，例如「打印机」命中日志类的「打印」，属规则化方案的固有代价