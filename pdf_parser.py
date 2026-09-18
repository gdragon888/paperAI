"""PDF 解析模块：提取页数与文本，并检测疑似扫描版。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

import pymupdf


# 平均每页字符数低于此阈值时，判定为疑似扫描版/无可提取文字
MIN_CHARS_PER_PAGE = 50
# 全文绝对下限（页数很少时也兜底）
MIN_TOTAL_CHARS = 80


@dataclass
class PDFExtractResult:
    """PDF 文本提取结果。"""

    filename: str
    page_count: int
    text: str
    char_count: int
    is_scanned: bool
    error: str | None = None


def extract_pdf_info(file_obj: BinaryIO, filename: str) -> PDFExtractResult:
    """从上传的 PDF 文件对象中提取页数与文本。

    Args:
        file_obj: 可读的二进制文件对象（如 Streamlit UploadedFile）。
        filename: 原始文件名，用于展示。

    Returns:
        PDFExtractResult，包含元信息、全文及是否疑似扫描版。
    """
    try:
        data = file_obj.read()
        if not data:
            return PDFExtractResult(
                filename=filename,
                page_count=0,
                text="",
                char_count=0,
                is_scanned=True,
                error="上传的文件为空，请重新选择 PDF。",
            )

        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            page_count = doc.page_count
            if page_count == 0:
                return PDFExtractResult(
                    filename=filename,
                    page_count=0,
                    text="",
                    char_count=0,
                    is_scanned=True,
                    error="PDF 没有可用页面，请检查文件是否损坏。",
                )

            parts: list[str] = []
            for page in doc:
                # 使用 get_text 提取纯文本；扫描版通常几乎为空
                page_text = page.get_text("text") or ""
                parts.append(page_text)

            text = "\n".join(parts).strip()
            char_count = len(text)
            is_scanned = _looks_like_scanned(page_count, char_count)

            return PDFExtractResult(
                filename=filename,
                page_count=page_count,
                text=text,
                char_count=char_count,
                is_scanned=is_scanned,
                error=None,
            )
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001 - 对用户展示友好错误即可
        return PDFExtractResult(
            filename=filename,
            page_count=0,
            text="",
            char_count=0,
            is_scanned=True,
            error=f"无法解析该 PDF：{exc}",
        )


def _looks_like_scanned(page_count: int, char_count: int) -> bool:
    """根据字符密度判断是否疑似扫描版或无可提取文字。"""
    if char_count < MIN_TOTAL_CHARS:
        return True
    avg = char_count / max(page_count, 1)
    return avg < MIN_CHARS_PER_PAGE
