"""本地持久化层：SQLite 存储论文、AI 总结与分类标签。

数据库文件固定为项目根目录下 data/paperai.db，全项目只通过本模块访问，
避免出现多个 db 文件写入不一致的问题。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# 数据库路径：与本文件同目录的 data/ 下（单一来源）
DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "paperai.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     TEXT NOT NULL UNIQUE,
    filename    TEXT NOT NULL,
    page_count  INTEGER NOT NULL DEFAULT 0,
    char_count  INTEGER NOT NULL DEFAULT 0,
    is_scanned  INTEGER NOT NULL DEFAULT 0,
    pdf_bytes   BLOB,
    paper_text  TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT NOT NULL,
    analyzed_at TEXT,
    model       TEXT,
    truncated   INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS paper_tags (
    paper_id INTEGER NOT NULL,
    tag_id   INTEGER NOT NULL,
    PRIMARY KEY (paper_id, tag_id),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id)   REFERENCES tags(id)   ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_papers_uploaded ON papers(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_paper_tags_tag  ON paper_tags(tag_id);
"""


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    """打开一个短连接，正常退出自动提交，异常回滚。"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """初始化数据表（幂等，可在每次应用启动时调用）。"""
    with _db() as conn:
        conn.executescript(_SCHEMA)


def _tags_of(conn: sqlite3.Connection, paper_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT t.name FROM tags t
        JOIN paper_tags pt ON pt.tag_id = t.id
        WHERE pt.paper_id = ?
        ORDER BY t.name COLLATE NOCASE
        """,
        (paper_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def _row_to_record(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """把数据库行转成界面使用的记录字典。"""
    record: dict[str, Any] = dict(row)
    record["is_scanned"] = bool(record.get("is_scanned"))
    record["truncated"] = bool(record.get("truncated"))
    raw_summary = record.get("summary_json")
    record["summary"] = json.loads(raw_summary) if raw_summary else None
    record.pop("summary_json", None)
    record["tags"] = _tags_of(conn, record["id"])
    return record


# ---------------------------------------------------------------- 论文记录


def insert_paper(
    *,
    file_id: str,
    filename: str,
    page_count: int,
    char_count: int,
    is_scanned: bool,
    paper_text: str,
    pdf_bytes: bytes | None,
) -> int:
    """上传解析后立即入库，返回新记录主键。"""
    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO papers (
                file_id, filename, page_count, char_count, is_scanned,
                pdf_bytes, paper_text, uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                filename,
                page_count,
                char_count,
                1 if is_scanned else 0,
                sqlite3.Binary(pdf_bytes) if pdf_bytes is not None else None,
                paper_text,
                _now(),
            ),
        )
        return int(cur.lastrowid)


def update_summary(
    paper_id: int,
    summary: dict[str, str],
    *,
    truncated: bool,
    model: str,
) -> None:
    """把一次 AI 结构化总结写回论文记录。"""
    with _db() as conn:
        conn.execute(
            """
            UPDATE papers SET summary_json = ?, truncated = ?,
                              model = ?, analyzed_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(summary, ensure_ascii=False),
                1 if truncated else 0,
                model,
                _now(),
                paper_id,
            ),
        )


def get_paper(paper_id: int) -> dict[str, Any] | None:
    """按主键读取单篇论文。"""
    with _db() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return _row_to_record(conn, row) if row else None


def get_paper_by_file_id(file_id: str) -> dict[str, Any] | None:
    """按「文件名-大小」指纹读取（同一文件不重复入库）。"""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM papers WHERE file_id = ?", (file_id,)
        ).fetchone()
        return _row_to_record(conn, row) if row else None


def list_papers(
    *,
    tag: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    """列出论文，可按标签与关键词（文件名/总结内容）过滤，新上传的在前。"""
    sql = "SELECT DISTINCT p.* FROM papers p"
    params: list[Any] = []
    where: list[str] = []

    if tag:
        sql += " JOIN paper_tags pt ON pt.paper_id = p.id JOIN tags t ON t.id = pt.tag_id"
        where.append("t.name = ? COLLATE NOCASE")
        params.append(tag)
    if keyword:
        like = f"%{keyword.strip()}%"
        where.append(
            "(p.filename LIKE ? OR p.summary_json LIKE ? OR p.paper_text LIKE ?)"
        )
        params.extend([like, like, like])

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.uploaded_at DESC, p.id DESC"

    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_record(conn, row) for row in rows]


def count_papers() -> int:
    """论文总数。"""
    with _db() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0])


def delete_paper(paper_id: int) -> None:
    """删除论文（关联标签映射随外键级联删除；空标签自动清理）。"""
    with _db() as conn:
        conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        conn.execute(
            "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM paper_tags)"
        )


# ---------------------------------------------------------------- 标签


def _normalize_tag_names(names: list[str]) -> list[str]:
    """去空白、去重（大小写不敏感），保持顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for raw in names:
        name = (raw or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _ensure_tag(conn: sqlite3.Connection, name: str) -> int:
    """确保标签存在并返回其 id（名称大小写不敏感）。"""
    row = conn.execute(
        "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
    return int(cur.lastrowid)


def set_paper_tags(paper_id: int, tag_names: list[str]) -> None:
    """整体覆盖一篇论文的标签（不存在的标签自动创建）。"""
    names = _normalize_tag_names(tag_names)
    with _db() as conn:
        conn.execute("DELETE FROM paper_tags WHERE paper_id = ?", (paper_id,))
        for name in names:
            tag_id = _ensure_tag(conn, name)
            conn.execute(
                "INSERT OR IGNORE INTO paper_tags (paper_id, tag_id) VALUES (?, ?)",
                (paper_id, tag_id),
            )
        # 清理未被任何论文使用的标签
        conn.execute(
            "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM paper_tags)"
        )


def get_all_tags() -> list[str]:
    """返回全部标签名（仅含至少被一篇论文使用的标签），按名称排序。"""
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT t.name FROM tags t
            WHERE EXISTS (SELECT 1 FROM paper_tags pt WHERE pt.tag_id = t.id)
            ORDER BY t.name COLLATE NOCASE
            """
        ).fetchall()
        return [r["name"] for r in rows]


def _now() -> str:
    """当前本地时间，秒级 ISO 字符串。"""
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")
