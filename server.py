"""MD Skill Checker MCP Server

只读扫描存放 Skill 定义的 Markdown 文件，按 6 个维度做规则化打分，
输出纯文本质检报告，交给上层 LLM 用于迭代优化 Skill 文档。

设计原则：
- 只读：不修改、不重写、不删除任何文件
- 规则化：纯关键词 / 结构特征匹配，不内置大模型，不依赖向量库
- 轻量：只依赖官方 mcp SDK（内置 FastMCP）
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("md-skill-checker")

DEFAULT_SKILL_DIR = "./skills"
MD_SUFFIXES = (".md", ".markdown")
EXCLUDED_STEMS = {"readme", "changelog", "license", "notice"}

# 判断一个 md 是不是 Skill 文档：命中 2 个及以上标记词即认为是
SKILL_MARKERS = ("skill", "技能", "步骤", "输入", "输出", "适用场景", "触发条件", "禁止")

# 步骤特征：编号列表 / 第N步 / 含“步骤”的小标题
STEP_PATTERN = re.compile(
    r"(?m)^\s*(?:#{2,6}[^\n]*步骤|\d+[.、)）]\s+\S|第[一二三四五六七八九十]+步|步骤\s*\d)"
)


@dataclass(frozen=True)
class Item:
    """一个打分小项：命中即得分，未命中记入缺失项并给出建议。"""

    points: int
    keywords: tuple[str, ...] = ()
    patterns: tuple[re.Pattern[str], ...] = ()
    min_hits: int = 1
    missing: str = ""
    advice: str = ""
    rule: str = ""


@dataclass(frozen=True)
class Dimension:
    name: str
    weight: int
    items: tuple[Item, ...]


# ---------------------------------------------------------------- 评审维度

DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        "技能目标清晰",
        20,
        (
            Item(
                8,
                keywords=("解决", "作用", "用于", "目标", "用途", "目的", "功能"),
                missing="未说明这个 skill 解决什么问题",
                advice="用一句话写明该 skill 的目标与要解决的问题",
            ),
            Item(
                6,
                keywords=("适用场景", "使用场景", "适用", "何时使用", "触发条件"),
                missing="没有写适用场景",
                advice="补充“适用场景 / 触发条件”，说明何时应该调用它",
            ),
            Item(
                6,
                keywords=("不适用", "禁止使用", "不要用于", "不推荐"),
                missing="没有写不适用场景",
                advice="补充“不适用场景”，规避被误触发",
            ),
        ),
    ),
    Dimension(
        "执行步骤完备",
        25,
        (
            Item(
                10,
                patterns=(STEP_PATTERN,),
                missing="没有可识别的步骤列表",
                advice="用有序列表把流程拆成编号步骤",
                rule="出现步骤编号列表、『第N步』或含“步骤”的小标题",
            ),
            Item(
                8,
                patterns=(STEP_PATTERN,),
                min_hits=3,
                missing="步骤少于 3 步，粒度太粗",
                advice="把流程拆到 3 步以上，每步只做一件事",
                rule="步骤条目至少 3 条",
            ),
            Item(
                7,
                keywords=("如果", "若", "判断", "校验", "确认", "否则", "分支", "满足"),
                missing="步骤里缺少判定条件 / 分支说明",
                advice="在关键步骤写明判定条件与分支（如果…则…否则…）",
            ),
        ),
    ),
    Dimension(
        "输入输出契约",
        20,
        (
            Item(
                7,
                keywords=("输入", "入参", "参数", "input", "需要提供", "依赖", "前置"),
                missing="没有说明输入是什么",
                advice="明确列出输入项、类型以及是否必填",
            ),
            Item(
                8,
                keywords=("输出", "返回", "格式", "json", "yaml", "schema", "字段", "报告"),
                missing="没有指定输出格式",
                advice="规定输出格式（JSON / 文本 / 表格）并说明关键字段",
            ),
            Item(
                5,
                keywords=("示例", "example", "schema", "```"),
                missing="缺少输入 / 输出示例",
                advice="补一段输入输出示例或 JSON schema",
            ),
        ),
    ),
    Dimension(
        "异常与兜底",
        15,
        (
            Item(
                6,
                keywords=("失败", "异常", "报错", "错误", "error", "fail"),
                missing="没有说明失败 / 异常情况",
                advice="列出可能失败的环节以及对应的错误信息",
            ),
            Item(
                5,
                keywords=("兜底", "fallback", "降级", "重试", "回退", "默认值", "默认"),
                missing="缺少兜底 / fallback 策略",
                advice="为失败路径给出兜底动作（降级、重试或返回默认值）",
            ),
            Item(
                4,
                keywords=("边界", "超时", "为空", "空值", "不存在", "极端", "timeout"),
                missing="没有覆盖边界情况",
                advice="补充边界场景：空输入、超长内容、超时、路径不存在等",
            ),
        ),
    ),
    Dimension(
        "约束与禁止行为",
        10,
        (
            Item(
                6,
                keywords=("禁止", "不要", "不得", "严禁", "不可", "never"),
                missing="缺少禁止行为描述",
                advice="明确写出禁止动作，避免 LLM 越界（如禁止写入文件、禁止猜测）",
            ),
            Item(
                4,
                keywords=("只读", "限制", "前提", "约束", "必须"),
                missing="没有写清前置条件与限制",
                advice="补充前置条件、权限范围与约束",
            ),
        ),
    ),
    Dimension(
        "可观测与日志",
        10,
        (
            Item(
                6,
                keywords=("日志", "log", "记录", "打印", "logging"),
                missing="没有日志 / 记录说明",
                advice="标注需要记录的日志内容",
            ),
            Item(
                4,
                keywords=("关键节点", "监控", "统计", "观测", "耗时", "trace"),
                missing="没有标注关键节点",
                advice="在关键节点输出状态、耗时或统计信息，便于排查",
            ),
        ),
    ),
)


# ---------------------------------------------------------------- 打分逻辑


@dataclass
class DimensionResult:
    name: str
    weight: int
    score: int = 0
    missing: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)


def _hit_count(text: str, item: Item) -> int:
    lowered = text.lower()
    hits = sum(1 for kw in item.keywords if kw.lower() in lowered)
    for pattern in item.patterns:
        hits += len(pattern.findall(text))
    return hits


def _evaluate(text: str) -> list[DimensionResult]:
    results: list[DimensionResult] = []
    for dim in DIMENSIONS:
        result = DimensionResult(dim.name, dim.weight)
        for item in dim.items:
            if _hit_count(text, item) >= item.min_hits:
                result.score += item.points
            else:
                result.missing.append(item.missing)
                result.advice.append(item.advice)
        results.append(result)
    return results


def _marker(score: int, weight: int) -> str:
    ratio = score / weight if weight else 0
    if ratio >= 0.9:
        return "✅"
    if ratio >= 0.6:
        return "⚠️"
    return "❌"


def _grade(total: int) -> str:
    if total >= 90:
        return "A｜优秀"
    if total >= 75:
        return "B｜良好"
    if total >= 60:
        return "C｜及格"
    return "D｜待改进"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _skill_root() -> Path:
    return Path(os.getenv("SKILL_DIR", DEFAULT_SKILL_DIR)).expanduser()


def _resolve(raw: str) -> Path:
    """相对路径按 SKILL_DIR 解析，绝对路径原样使用。"""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _skill_root() / path
    return path.resolve()


def _looks_like_skill(path: Path, text: str) -> bool:
    if path.stem.lower() in EXCLUDED_STEMS:
        return False
    lowered = text.lower()
    return sum(1 for marker in SKILL_MARKERS if marker.lower() in lowered) >= 2


def _format_report(path: Path, text: str) -> str:
    results = _evaluate(text)
    total = sum(r.score for r in results)

    lines = [
        "Skill 质检报告",
        f"文件：{path}",
        f"总分：{total}/100（{_grade(total)}）",
        "",
    ]
    for result in results:
        detail = "；".join(result.missing) if result.missing else "结构完整"
        lines.append(
            f"【{result.name}】{result.score}/{result.weight} "
            f"{_marker(result.score, result.weight)} {detail}"
        )

    missing = [m for r in results for m in r.missing]
    advice = [a for r in results for a in r.advice]

    lines.append("")
    if missing:
        lines.append(f"缺失项（{len(missing)}）：")
        lines.extend(f"- {m}" for m in missing)
    else:
        lines.append("缺失项：无，6 个维度全部命中规则。")

    if advice:
        lines.append("优化建议：")
        lines.extend(f"{i}. {a}" for i, a in enumerate(advice, 1))

    lines.append("")
    lines.append("说明：本次仅做规则化检测，未修改任何文件；文档改写请由上层 LLM 完成。")
    return "\n".join(lines)


def _criteria_text() -> str:
    lines = ["MD Skill Checker 评分规则（总分 100，规则化匹配）", ""]
    for dim in DIMENSIONS:
        lines.append(f"【{dim.name}】{dim.weight} 分")
        for item in dim.items:
            rule = item.rule or "命中任一关键词：" + " / ".join(item.keywords)
            extra = (
                f"（需命中 ≥{item.min_hits} 处）" if item.min_hits > 1 and not item.rule else ""
            )
            lines.append(f"- {item.points} 分：{rule}{extra}")
        lines.append("")
    lines.append("判定方式：小项独立命中，命中得分、未命中记入缺失项，分值累加为总分。")
    lines.append("等级：≥90 A｜优秀，≥75 B｜良好，≥60 C｜及格，<60 D｜待改进。")
    lines.append("说明：只判断规范要素是否齐备，不评价语义质量；修改建议供上层 LLM 参考。")
    return "\n".join(lines)


# ---------------------------------------------------------------- MCP Tools


@mcp.tool()
def check_skill_md(file_path: str) -> str:
    """校验单个 Skill Markdown 文件，返回总分、分项得分、缺陷清单与优化建议（只读，不修改文件）。

    Args:
        file_path: Skill 文档路径。支持绝对路径，或相对 SKILL_DIR 的路径。
    """
    path = _resolve(file_path)
    if not path.exists():
        return f"❌ 文件不存在：{path}\n可传绝对路径，或设置 SKILL_DIR 环境变量指定根目录。"
    if not path.is_file():
        return f"❌ 不是文件：{path}"
    if path.suffix.lower() not in MD_SUFFIXES:
        return f"❌ 只支持 Markdown 文件（.md / .markdown）：{path.name}"
    text = _read_text(path)
    if not text.strip():
        return f"❌ 文件内容为空：{path}"
    return _format_report(path, text)


@mcp.tool()
def scan_skill_dir(dir_path: str = "") -> str:
    """批量扫描目录下所有 Markdown，自动识别 Skill 文档并生成汇总质检报告（只读）。

    Args:
        dir_path: 要扫描的目录。为空时使用 SKILL_DIR；相对路径按 SKILL_DIR 解析。
    """
    root = _resolve(dir_path) if dir_path else _skill_root().resolve()
    if not root.exists():
        return f"❌ 目录不存在：{root}\n可通过 SKILL_DIR 环境变量指定 skill 目录。"
    if not root.is_dir():
        return f"❌ 不是目录：{root}"

    candidates = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in MD_SUFFIXES
        and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )
    md_files = [p for p in candidates if p.stem.lower() not in EXCLUDED_STEMS]
    ignored = len(candidates) - len(md_files)
    if not md_files:
        return f"⚠️ 目录下没有可校验的 Markdown 文件：{root}"

    rows: list[tuple[int, Path, str]] = []
    suspected: list[str] = []
    for path in md_files:
        name = path.relative_to(root).as_posix()
        text = _read_text(path)
        if not _looks_like_skill(path, text):
            # 宁可多打分也不隐藏：写得差的 skill 往往命不中标记词
            suspected.append(name)
        if not text.strip():
            rows.append((0, path, "文件为空，无法打分"))
            continue
        results = _evaluate(text)
        total = sum(r.score for r in results)
        weakest = sorted(results, key=lambda r: r.score / r.weight)
        if weakest[0].score >= weakest[0].weight * 0.9:
            brief = "无明显短板"
        else:
            brief = "、".join(f"{r.name} {r.score}/{r.weight}" for r in weakest[:2])
        rows.append((total, path, brief))
    rows.sort(key=lambda row: (row[0], row[1].name))  # 低分优先，先看短板

    header = f"扫描 {len(md_files)} 个 Markdown"
    if ignored:
        header += f"（已忽略 README / changelog / license 等 {ignored} 个）"
    lines = ["Skill 库巡检报告", f"目录：{root}", header, ""]
    for index, (total, path, brief) in enumerate(rows, 1):
        name = path.relative_to(root).as_posix()
        flag = "（疑似非 Skill）" if name in suspected else ""
        lines.append(f"[{index}] {total}/100 {_grade(total)} {name}{flag}")
        lines.append(f"     短板：{brief}")

    if suspected:
        lines.append("")
        lines.append(
            "疑似非 Skill：标记词命中不足 2 个，仍已按规则打分供参考 —— "
            + "、".join(suspected)
        )

    scores = [row[0] for row in rows]
    lines.append("")
    lines.append(
        f"汇总：平均 {sum(scores) / len(scores):.1f} 分，"
        f"最高 {max(scores)} 分（{rows[-1][1].name}），最低 {min(scores)} 分（{rows[0][1].name}）"
    )
    lines.append(f"优先优化：{rows[0][1].relative_to(root).as_posix()}")
    lines.append("说明：仅做规则化巡检，未修改任何文件；可用 check_skill_md 查看单个文档的完整报告。")
    return "\n".join(lines)


@mcp.tool()
def get_check_criteria() -> str:
    """返回完整的评分规则原文（6 个维度、权重、命中规则），可用于让 LLM 按规范撰写新的 Skill。"""
    return _criteria_text()


if __name__ == "__main__":
    mcp.run(transport="stdio")