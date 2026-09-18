"""AI 分析模块：结构化总结与基于原文的问答。"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)


# 约对应常见小模型上下文中的安全节选长度（字符，非 token）
DEFAULT_MAX_CHARS = 28000

# SDK 默认连接超时仅 5 秒，网络稍慢就会直接抛 “Request timed out”
DEFAULT_CONNECT_TIMEOUT_SECONDS = 20.0
DEFAULT_READ_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_RETRIES = 3

SUMMARY_FIELDS = [
    ("basic_info", "论文基本信息"),
    ("one_sentence", "一句话总结"),
    ("background", "研究背景"),
    ("purpose", "研究目的/研究问题"),
    ("subjects", "研究对象"),
    ("data_source", "数据来源"),
    ("study_design", "研究设计"),
    ("methods", "研究方法"),
    ("statistics", "统计分析方法"),
    ("results", "核心结果"),
    ("innovation", "创新点"),
    ("limitations", "局限性"),
    ("keywords", "关键词"),
]

SYSTEM_PROMPT = """你是严谨的科研论文阅读助手，面向研究生与科研人员。
你必须严格依据用户提供的论文原文作答，遵守以下规则：
1. 只陈述论文中明确写出的内容；不得把推测、常识或外部知识写成论文事实。
2. 论文未提及的字段，必须原样填写：「论文未说明」。
3. 原文表述模糊、证据不足时，在该字段开头写「不确定：」再简要说明依据。
4. 重点关注医学、生物医学、科研数据分析相关信息：样本/研究对象、数据来源、研究设计、干预或暴露、结局指标、统计分析方法、效应量与显著性等。
5. 使用简洁、专业的中文。
6. 只输出一个 JSON 对象，不要 Markdown 代码块，不要额外解释。
JSON 的键必须恰好为：
basic_info, one_sentence, background, purpose, subjects, data_source,
study_design, methods, statistics, results, innovation, limitations, keywords
各值为字符串；keywords 可用顿号或逗号分隔。
basic_info 尽量包含：标题、作者、期刊/会议、年份（仅原文有的写）。
"""

QA_SYSTEM_PROMPT = """你是严谨的科研论文问答助手。
规则：
1. 只根据用户提供的论文原文回答；不得把外部知识或主观推测写成论文事实。
2. 原文没有相关信息时，明确回答「论文未说明」，并可简要说明缺什么信息。
3. 证据不足时，用「不确定：」开头，并指出依据局限。
4. 回答简洁、专业，使用中文；必要时可分点列出。
5. 若问题涉及复现研究所需数据，仅根据原文列出论文实际提到的数据/材料/来源；原文未写的不要编造。
"""

# 页面快捷问题
QUICK_QUESTIONS = [
    "这篇论文的创新点是什么？",
    "这篇论文使用了什么研究方法？",
    "数据来源是什么？",
    "使用了哪些统计分析方法？",
    "这篇论文有哪些局限？",
    "如果我要复现这项研究，需要哪些数据？",
]


def _secret(name: str) -> str:
    """读取 Streamlit secrets（云端部署用）。

    仅在 Streamlit 运行时中查询，本地脚本直接返回空串，避免额外开销。
    """
    module = sys.modules.get("streamlit")
    if module is None:
        return ""
    try:
        value = module.secrets.get(name, "")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - 无 secrets.toml 或未配置该键
        return ""
    return str(value).strip() if value else ""


def _config(name: str, default: str = "") -> str:
    """配置读取顺序：环境变量/.env > Streamlit secrets > 默认值。"""
    return os.getenv(name, "").strip() or _secret(name) or default


def _env_float(name: str, default: float) -> float:
    """读取正数浮点型环境变量，缺失或非法时回退默认值。"""
    raw = _config(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _build_timeout() -> Any:
    """构造分阶段超时配置：连接短、读写长，避免大论文生成被误判超时。"""
    read_timeout = _env_float("OPENAI_TIMEOUT", DEFAULT_READ_TIMEOUT_SECONDS)
    connect_timeout = _env_float(
        "OPENAI_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT_SECONDS
    )
    try:
        import httpx2 as _http_client  # openai 3.x 使用的 HTTP 客户端
    except ImportError:
        try:
            import httpx as _http_client  # 兼容旧版 openai SDK
        except ImportError:
            return read_timeout
    return _http_client.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=read_timeout,
        pool=connect_timeout,
    )


def _get_client() -> OpenAI:
    """从环境变量创建 OpenAI 客户端。"""
    load_dotenv()
    api_key = _config("OPENAI_API_KEY")
    if not api_key or api_key == "sk-your-key-here":
        raise ValueError(
            "未配置有效的 OPENAI_API_KEY。本地请复制 .env.example 为 .env 并填入密钥；"
            "Streamlit Cloud 部署请在应用设置的 Secrets 中配置。"
        )

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": _build_timeout(),
        "max_retries": int(_env_float("OPENAI_MAX_RETRIES", DEFAULT_MAX_RETRIES)),
    }
    base_url = _config("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _get_model() -> str:
    """读取模型名称，默认 gpt-4o-mini。"""
    load_dotenv()
    return _config("OPENAI_MODEL", "gpt-4o-mini")


def _build_extra_body() -> dict[str, Any]:
    """兼容接口的额外请求参数。

    DeepSeek 新一代模型默认开启思考模式（耗时长、按思考 token 计费），
    结构化抽取场景不需要，显式关闭；其他接口返回空 dict，不产生影响。
    """
    base_url = _config("OPENAI_BASE_URL").lower()
    if "deepseek.com" in base_url:
        return {"thinking": {"type": "disabled"}}
    return {}


def _friendly_error(exc: Exception) -> str:
    """把 SDK 异常翻译成可操作的中文提示。"""
    detail = str(exc)
    lowered = detail.lower()

    # 注意：APITimeoutError 是 APIConnectionError 的子类，必须先判断
    if isinstance(exc, APITimeoutError):
        return (
            "请求超时。常见原因是本机到 api.openai.com 的网络不稳定或需要代理。"
            "可在 .env 中调大 OPENAI_TIMEOUT（读写超时，单位秒），"
            "或设置 OPENAI_BASE_URL 指向可访问的兼容接口。"
        )
    if isinstance(exc, AuthenticationError):
        return "鉴权失败（401）：OPENAI_API_KEY 无效或已被吊销，请更新 .env 中的密钥。"
    if isinstance(exc, RateLimitError):
        if "insufficient_quota" in lowered or "credit_balance" in lowered:
            return (
                "账户额度不足（429 insufficient_quota）："
                "该 Key 所属账户没有可用余额/额度，请到 OpenAI 后台充值或改用其他 Key。"
            )
        return f"请求过于频繁或超出配额（429）：{detail}"
    if isinstance(exc, APIConnectionError):
        return (
            "无法连接到 api.openai.com（网络层失败）。"
            "请检查网络或代理，也可在 .env 中设置 OPENAI_BASE_URL 指向可访问的兼容接口。"
        )
    return f"{type(exc).__name__}: {detail}"


def prepare_paper_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    """截断过长论文文本，控制 LLM 上下文长度。

    Returns:
        (用于模型的文本, 是否发生了截断)
    """
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned, False

    # 优先保留开头（摘要/引言）与结尾附近（讨论/结论）各一段
    head_size = int(max_chars * 0.7)
    tail_size = max_chars - head_size
    head = cleaned[:head_size]
    tail = cleaned[-tail_size:]
    combined = (
        head
        + "\n\n[……中间部分因长度限制已省略……]\n\n"
        + tail
    )
    return combined, True


def _empty_summary(note: str = "论文未说明") -> dict[str, str]:
    """生成各字段默认值。"""
    return {key: note for key, _ in SUMMARY_FIELDS}


def _parse_summary_json(raw: str) -> dict[str, str]:
    """从模型输出中解析 JSON，并补齐缺失字段。"""
    text = raw.strip()
    # 容错：去掉可能的 ```json 包裹
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 再尝试截取第一个 { ... }
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            raise

    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象。")

    result = _empty_summary()
    for key, _ in SUMMARY_FIELDS:
        value = data.get(key)
        if value is None or str(value).strip() == "":
            result[key] = "论文未说明"
        else:
            result[key] = str(value).strip()
    return result


def summarize_paper(paper_text: str) -> dict[str, Any]:
    """根据论文原文生成结构化阅读总结。

    Returns:
        {
          "summary": {字段: 内容},
          "truncated": bool,
          "model": str,
          "error": str | None,
        }
    """
    used_text, truncated = prepare_paper_text(paper_text)
    if not used_text:
        return {
            "summary": _empty_summary(),
            "truncated": False,
            "model": _get_model(),
            "error": "论文文本为空，无法分析。",
        }

    user_prompt = (
        "请根据下列论文原文生成结构化阅读总结。"
        "若文中标注了省略，表示仅基于节选内容判断，不确定处请标记「不确定：」。\n\n"
        f"===== 论文原文开始 =====\n{used_text}\n===== 论文原文结束 ====="
    )

    try:
        client = _get_client()
        model = _get_model()
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            extra_body=_build_extra_body(),
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            return {
                "summary": _empty_summary(),
                "truncated": truncated,
                "model": model,
                "error": "模型返回空内容，请稍后重试。",
            }

        summary = _parse_summary_json(content)
        if truncated:
            note = (
                "（说明：论文较长，本次分析基于开头与结尾节选，"
                "部分中间章节可能未覆盖。）"
            )
            summary["basic_info"] = f"{summary['basic_info']}\n{note}".strip()

        return {
            "summary": summary,
            "truncated": truncated,
            "model": model,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "summary": _empty_summary(),
            "truncated": truncated,
            "model": _get_model(),
            "error": f"生成总结失败：{_friendly_error(exc)}",
        }


def ask_paper(paper_text: str, question: str) -> dict[str, Any]:
    """基于当前论文原文回答用户问题。

    Returns:
        {"answer": str, "truncated": bool, "model": str, "error": str | None}
    """
    q = (question or "").strip()
    used_text, truncated = prepare_paper_text(paper_text)
    model = _get_model()

    if not q:
        return {
            "answer": "",
            "truncated": truncated,
            "model": model,
            "error": "请输入问题。",
        }
    if not used_text:
        return {
            "answer": "",
            "truncated": False,
            "model": model,
            "error": "论文文本为空，无法问答。",
        }

    user_prompt = (
        "请仅根据下列论文原文回答问题。"
        "若文中标注了省略，表示仅基于节选，不确定处请标记「不确定：」。\n\n"
        f"===== 论文原文开始 =====\n{used_text}\n===== 论文原文结束 =====\n\n"
        f"问题：{q}"
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": QA_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            extra_body=_build_extra_body(),
        )
        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            return {
                "answer": "",
                "truncated": truncated,
                "model": model,
                "error": "模型返回空内容，请稍后重试。",
            }
        if truncated:
            answer += (
                "\n\n（说明：论文较长，本次回答基于开头与结尾节选，"
                "请结合原文核对。）"
            )
        return {
            "answer": answer,
            "truncated": truncated,
            "model": model,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "answer": "",
            "truncated": truncated,
            "model": model,
            "error": f"问答失败：{_friendly_error(exc)}",
        }
