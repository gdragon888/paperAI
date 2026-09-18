"""PaperAI — 科研论文智能阅读助手（Streamlit 入口）。"""

from __future__ import annotations

import html
import re

import streamlit as st

from ai_analyzer import QUICK_QUESTIONS, SUMMARY_FIELDS, ask_paper, summarize_paper
from export_utils import default_export_filename, summary_to_markdown
from pdf_parser import extract_pdf_info
import storage


def _inject_styles() -> None:
    """注入简洁、偏学术风格的页面样式。"""
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1100px; }
        h1 { letter-spacing: 0.02em; margin-bottom: 0.2rem !important; }
        .paperai-subtitle {
            color: #4a5568;
            font-size: 1.05rem;
            margin-bottom: 0.8rem;
        }
        .paperai-section-title {
            font-size: 1.15rem;
            font-weight: 650;
            color: #1a202c;
            margin: 0.4rem 0 0.8rem 0;
            padding-bottom: 0.35rem;
            border-bottom: 2px solid #2c5282;
        }
        .paperai-tag {
            display: inline-block;
            background: #ebf4ff;
            color: #2c5282;
            border-radius: 999px;
            padding: 0.1rem 0.7rem;
            margin: 0 0.35rem 0.35rem 0;
            font-size: 0.85rem;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1rem !important;
            word-break: break-all;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _section_title(text: str) -> None:
    """渲染分区标题。"""
    st.markdown(f'<div class="paperai-section-title">{text}</div>', unsafe_allow_html=True)


def _split_tag_text(text: str) -> list[str]:
    """把逗号/顿号/分号分隔的标签文本拆成列表。"""
    return [part for part in re.split(r"[,，、;；/]+", text or "") if part.strip()]


def _fmt_time(iso_text: str | None) -> str:
    """ISO 时间转成易读形式。"""
    if not iso_text:
        return "—"
    return iso_text.replace("T", " ")[:16]


# ---------------------------------------------------------------- 标签编辑


def _render_tag_editor(record: dict) -> None:
    """为一篇论文提供标签选择、新建与「按 AI 关键词生成」功能。"""
    paper_id = record["id"]
    current = list(record.get("tags") or [])
    options = sorted(set(storage.get_all_tags()) | set(current), key=str.lower)

    with st.container(border=True):
        st.markdown("**标签分类**")
        chosen = st.multiselect(
            "选择已有标签",
            options=options,
            default=current,
            key=f"tag_select_{paper_id}",
            label_visibility="collapsed" if current else "visible",
        )
        new_text = st.text_input(
            "新标签",
            key=f"tag_new_{paper_id}",
            placeholder="添加新标签，多个用逗号或顿号分隔，例如：医学、Meta分析",
            label_visibility="collapsed",
        )
        col_a, col_b = st.columns(2)
        if col_a.button("保存标签", key=f"tag_save_{paper_id}", type="primary",
                        use_container_width=True):
            storage.set_paper_tags(paper_id, chosen + _split_tag_text(new_text))
            st.success("标签已保存。")
            st.rerun()

        keywords = (record.get("summary") or {}).get("keywords", "")
        if col_b.button(
            "用 AI 关键词生成标签",
            key=f"tag_ai_{paper_id}",
            use_container_width=True,
            disabled=not keywords,
            help="需要先生成 AI 总结（使用其「关键词」字段）",
        ):
            storage.set_paper_tags(paper_id, chosen + _split_tag_text(keywords))
            st.rerun()

        if current:
            chips = "".join(
                f'<span class="paperai-tag">{html.escape(name)}</span>'
                for name in current
            )
            st.markdown(chips, unsafe_allow_html=True)


# ---------------------------------------------------------------- 总结展示


def _render_summary_cards(summary: dict[str, str]) -> None:
    """以模块/卡片形式展示结构化总结。"""
    with st.container(border=True):
        st.markdown("**一句话总结**")
        st.write(summary.get("one_sentence", "论文未说明"))

    display_fields = [
        (k, label) for k, label in SUMMARY_FIELDS if k != "one_sentence"
    ]
    for i in range(0, len(display_fields), 2):
        cols = st.columns(2)
        for col, (key, label) in zip(cols, display_fields[i : i + 2]):
            with col:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.write(summary.get(key, "论文未说明"))


def _render_export(summary: dict[str, str], filename: str, truncated: bool) -> None:
    """提供 Markdown 下载。"""
    md = summary_to_markdown(
        summary,
        source_filename=filename,
        truncated=truncated,
    )
    st.download_button(
        label="导出阅读总结（Markdown）",
        data=md.encode("utf-8"),
        file_name=default_export_filename(filename),
        mime="text/markdown",
        use_container_width=False,
    )


# ---------------------------------------------------------------- 问答


def _run_qa(paper_text: str, question: str, qa_key: str) -> None:
    """执行一次问答并写入 session_state。"""
    with st.spinner("正在根据论文内容回答…"):
        st.session_state[f"qa_result_{qa_key}"] = ask_paper(paper_text, question)
    st.session_state[f"qa_question_{qa_key}"] = question


def _render_qa_section(paper_text: str, qa_key: str) -> None:
    """渲染论文问答区与快捷问题（qa_key 保证多篇论文同页时控件不冲突）。"""
    result_key = f"qa_result_{qa_key}"
    question_key = f"qa_question_{qa_key}"

    st.markdown("**快捷问题**")
    for i in range(0, len(QUICK_QUESTIONS), 2):
        cols = st.columns(2)
        for col, q in zip(cols, QUICK_QUESTIONS[i : i + 2]):
            with col:
                if st.button(
                    q,
                    key=f"quick_{qa_key}_{i}_{QUICK_QUESTIONS.index(q)}",
                    use_container_width=True,
                ):
                    _run_qa(paper_text, q, qa_key)

    with st.form(f"qa_form_{qa_key}", clear_on_submit=False):
        question = st.text_input(
            "输入你的问题",
            value=st.session_state.get(question_key, ""),
            placeholder="例如：样本量是多少？主要结局指标是什么？",
        )
        submitted = st.form_submit_button("提问", type="primary")

    if submitted:
        _run_qa(paper_text, question, qa_key)

    qa = st.session_state.get(result_key)
    if qa is None:
        return

    if qa.get("error"):
        st.error(qa["error"])
        return

    st.markdown("**回答**")
    with st.container(border=True):
        if st.session_state.get(question_key):
            st.markdown(f"*问题：{st.session_state[question_key]}*")
        st.markdown(qa.get("answer", ""))


# ---------------------------------------------------------------- 记录工作区


def _render_workspace(record: dict) -> None:
    """一篇已入库论文的完整工作区：信息、分析、标签、问答（上传页与文库共用）。"""
    paper_id = record["id"]

    _section_title("论文文件信息")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        with st.container(border=True):
            st.markdown("**文件名称**")
            st.write(record["filename"])
    with col2:
        with st.container(border=True):
            st.markdown("**页数**")
            st.write(str(record["page_count"]))
    with col3:
        with st.container(border=True):
            st.markdown("**提取文本长度**")
            st.write(f"{record['char_count']:,} 字符")
    with col4:
        with st.container(border=True):
            st.markdown("**上传时间**")
            st.write(_fmt_time(record["uploaded_at"]))

    if record["is_scanned"]:
        st.warning(
            "未能从该 PDF 中提取到足够文字，可能是扫描版或图片型 PDF。"
            "当前版本不支持 OCR，请上传可选中文字的文字版 PDF。"
        )
        return

    with st.expander("文本预览（前 1500 字符）", expanded=False):
        preview = record["paper_text"][:1500]
        if len(record["paper_text"]) > 1500:
            preview += "\n\n…（后续内容已省略）"
        st.text(preview)

    # —— 结构化总结（已生成则直接展示历史结果，否则可现场生成并落库）——
    st.markdown("")
    _section_title("结构化分析")
    summary = record.get("summary")
    if summary is None:
        analyze_col, tip_col = st.columns([1, 3])
        with analyze_col:
            start = st.button("开始分析", type="primary", use_container_width=True,
                              key=f"analyze_{paper_id}")
        with tip_col:
            st.caption("将依据论文原文生成阅读总结；缺失信息标记为「论文未说明」。")

        if start:
            with st.spinner("正在生成总结…"):
                analysis = summarize_paper(record["paper_text"])
            if analysis.get("error"):
                st.error(analysis["error"])
            else:
                storage.update_summary(
                    paper_id,
                    analysis["summary"],
                    truncated=bool(analysis.get("truncated")),
                    model=analysis.get("model", ""),
                )
                st.success("总结已生成并保存，下次打开仍可查看。")
                st.rerun()
    else:
        st.caption(f"分析时间：{_fmt_time(record.get('analyzed_at'))}｜模型：{record.get('model') or '—'}")
        if record.get("truncated"):
            st.warning(
                "论文较长，已自动截取开头与结尾部分送入模型；"
                "中间章节可能未完全覆盖，请结合原文核对。"
            )
        _render_summary_cards(summary)
        st.markdown("")
        _render_export(summary, record["filename"], bool(record.get("truncated")))

    # —— 标签分类 ——
    st.markdown("")
    _render_tag_editor(record)

    # —— 问答 ——
    st.markdown("---")
    _section_title("AI 论文问答")
    st.caption("回答严格基于当前上传论文的原文；未提及的内容会标明「论文未说明」。")
    _render_qa_section(record["paper_text"], qa_key=str(paper_id))


# ---------------------------------------------------------------- 上传页


def _get_or_create_paper(uploaded) -> dict | None:
    """同一文件直接返回已存记录；新文件解析后立即入库。"""
    file_id = f"{uploaded.name}-{uploaded.size}"
    existing = storage.get_paper_by_file_id(file_id)
    if existing is not None:
        return existing

    with st.spinner("正在解析论文…"):
        result = extract_pdf_info(uploaded, uploaded.name)
    if result.error:
        st.error(result.error)
        return None

    paper_id = storage.insert_paper(
        file_id=file_id,
        filename=result.filename,
        page_count=result.page_count,
        char_count=result.char_count,
        is_scanned=result.is_scanned,
        paper_text=result.text,
        pdf_bytes=uploaded.getvalue(),
    )
    st.session_state["last_uploaded_id"] = paper_id
    return storage.get_paper(paper_id)


def _render_upload_page() -> None:
    """上传与分析页。"""
    uploaded = st.file_uploader(
        "上传 PDF 论文",
        type=["pdf"],
        help="请上传文字版 PDF（扫描版暂不支持 OCR）。",
    )
    if uploaded is None:
        st.info("请上传一篇 PDF 论文以开始。同一文件重复上传会直接读取已保存的记录。")
        return

    record = _get_or_create_paper(uploaded)
    if record is None:
        return
    if record.get("summary"):
        st.success("已读取该论文此前保存的总结记录（无需重新分析）。")
    st.markdown("---")
    _render_workspace(record)


# ---------------------------------------------------------------- 文库页


def _render_delete_button(record: dict) -> None:
    """两步确认删除，避免误操作。"""
    paper_id = record["id"]
    flag_key = f"delete_confirm_{paper_id}"
    if st.session_state.get(flag_key):
        col_yes, col_no = st.columns(2)
        if col_yes.button("确认删除（不可恢复）", key=f"delete_yes_{paper_id}",
                          type="primary", use_container_width=True):
            storage.delete_paper(paper_id)
            st.session_state.pop(flag_key, None)
            st.rerun()
        if col_no.button("取消", key=f"delete_no_{paper_id}", use_container_width=True):
            st.session_state.pop(flag_key, None)
            st.rerun()
    else:
        if st.button("🗑 删除该记录", key=f"delete_btn_{paper_id}"):
            st.session_state[flag_key] = True
            st.rerun()


def _render_library_page() -> None:
    """我的文库：历史论文列表、标签筛选、回看总结与标签管理。"""
    _section_title("我的文库")

    total = storage.count_papers()
    if total == 0:
        st.info("文库还是空的。请到「上传分析」页上传第一篇论文，总结会自动保存在这里。")
        return

    all_tags = storage.get_all_tags()
    filter_col, search_col = st.columns([1, 2])
    tag_filter = filter_col.selectbox("按标签筛选", ["全部标签"] + all_tags)
    keyword = search_col.text_input(
        "搜索",
        placeholder="按文件名 / 总结内容 / 正文关键词搜索…",
    )

    records = storage.list_papers(
        tag=None if tag_filter == "全部标签" else tag_filter,
        keyword=keyword or None,
    )
    st.caption(f"符合条件：{len(records)} 篇｜文库总计：{total} 篇")
    if not records:
        st.warning("没有符合筛选条件的论文，试试更换标签或关键词。")
        return

    for record in records:
        tags = record.get("tags") or []
        status = "📄 已分析" if record.get("summary") else "📥 仅上传"
        tag_part = "｜标签：" + "、".join(tags) if tags else "｜未分类"
        label = (
            f"{status}｜{record['filename']}｜上传于 {_fmt_time(record['uploaded_at'])}"
            f"{tag_part}"
        )
        with st.expander(label, expanded=False):
            _render_delete_button(record)
            _render_workspace(record)


# ---------------------------------------------------------------- 入口


def main() -> None:
    """渲染首页：上传、解析、总结、问答、文库与标签。"""
    st.set_page_config(
        page_title="PaperAI",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    storage.init_db()
    _inject_styles()

    st.title("PaperAI")
    st.markdown(
        '<p class="paperai-subtitle">科研论文智能阅读助手</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        "上传文字版 PDF → 提取内容 → AI 结构化总结 / 问答 → 自动存入本地文库并支持标签分类。"
        "结论请务必对照原文核实。"
    )

    page = st.sidebar.radio("导航", ["📤 上传分析", "📚 我的文库"])
    st.sidebar.caption(f"本地文库已保存：{storage.count_papers()} 篇论文")
    st.sidebar.markdown("---")
    st.sidebar.caption("数据保存在本项目 data/paperai.db，仅存于本机。")

    st.markdown("---")
    if page.startswith("📤"):
        _render_upload_page()
    else:
        _render_library_page()


if __name__ == "__main__":
    main()
