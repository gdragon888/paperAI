"""将 AI 结构化总结导出为 Markdown。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ai_analyzer import SUMMARY_FIELDS


def summary_to_markdown(
    summary: dict[str, str],
    *,
    source_filename: str = "",
    truncated: bool = False,
) -> str:
    """把结构化总结字典转为 Markdown 文本。"""
    lines: list[str] = [
        "# PaperAI 论文阅读总结",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if source_filename:
        lines.append(f"- 来源文件：`{source_filename}`")
    if truncated:
        lines.append(
            "- 说明：原文较长，总结基于开头与结尾节选，请结合原文核对。"
        )
    lines.extend(
        [
            "",
            "> 本总结由 AI 依据论文原文生成；标注「论文未说明」或「不确定：」的内容请以原文为准。",
            "",
        ]
    )

    for key, label in SUMMARY_FIELDS:
        content = (summary.get(key) or "论文未说明").strip()
        lines.append(f"## {label}")
        lines.append("")
        lines.append(content)
        lines.append("")

    lines.append("---")
    lines.append("*由 PaperAI 导出*")
    lines.append("")
    return "\n".join(lines)


def default_export_filename(source_filename: str = "") -> str:
    """根据源 PDF 名生成默认下载文件名。"""
    stem = Path(source_filename).stem if source_filename else "paper"
    # 去掉路径不安全字符
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    safe = safe.strip("_") or "paper"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"PaperAI_{safe}_{stamp}.md"
