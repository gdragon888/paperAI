# PaperAI

科研论文智能阅读助手：上传 PDF，提取文本，生成 AI 结构化阅读总结，支持基于原文的问答，并可导出 Markdown。

> 第一版功能已齐备：PDF 提取 · AI 总结 · AI 问答 · Markdown 导出。

## 技术栈

- Python 3.11+
- Streamlit
- PyMuPDF
- OpenAI API
- python-dotenv

## 安装

```bash
cd PaperAI
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# 或 Windows CMD
.venv\Scripts\activate.bat

pip install -r requirements.txt
```

## 配置 API Key

1. 复制 `.env.example` 为 `.env`
2. 将 `OPENAI_API_KEY=` 后面换成你的密钥
3. **不要**把 `.env` 提交到 Git（已在 `.gitignore` 中忽略）

可选环境变量：

```bash
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_CONNECT_TIMEOUT=20
OPENAI_TIMEOUT=180
OPENAI_MAX_RETRIES=3
# HTTPS_PROXY=http://127.0.0.1:7890
```

## 运行

```bash
streamlit run app.py
```

浏览器打开后：

1. 上传文字版 PDF  
2. 查看文件名、页数、文本长度  
3. 点击「开始分析」生成结构化总结，并可导出 Markdown  
4. 使用快捷问题或自定义提问进行 AI 问答  

## 部署到公网（获得网页地址）

本应用是 Streamlit 服务，需要 Python 运行环境，不能直接托管到静态站点（GitHub Pages / Vercel / Netlify）。

### 方式一：Streamlit Community Cloud（免费，推荐）

1. 把项目推到 GitHub 仓库（`.env` 已被忽略，密钥不会上传）
2. 打开 <https://share.streamlit.io>，用 GitHub 账号登录，点「New app」
3. 选择仓库与分支，Main file path 填 `app.py`
4. 点「Advanced settings」→「Secrets」，粘贴：

```toml
OPENAI_API_KEY = "sk-proj-..."
OPENAI_MODEL = "gpt-4o-mini"
```

5. 点 Deploy，等待构建完成后即得到 `https://<应用名>.streamlit.app` 地址

配置读取顺序：环境变量 / `.env` > Streamlit secrets > 默认值。

### 方式二：临时公网地址（不部署）

本机启动 `streamlit run app.py` 后，用隧道工具把 8501 端口暴露到公网：

```bash
cloudflared tunnel --url http://localhost:8501
```

不用注册部署，但电脑必须一直开着。

### 公开部署前请注意

- 应用没有登录验证，拿到链接的任何人都能消耗你的 API 额度
- 账户无余额时，部署后依然会返回 429 insufficient_quota

## 项目结构

```text
PaperAI/
├── app.py           # Streamlit 界面入口
├── pdf_parser.py    # PDF 页数与文本提取
├── ai_analyzer.py   # OpenAI 结构化总结与问答
├── export_utils.py  # 总结导出为 Markdown
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 功能说明

| 模块 | 说明 |
|------|------|
| PDF 解析 | 提取文字；扫描版给出友好提示（不做 OCR） |
| AI 总结 | 基本信息、背景、方法、统计、结果、创新点、局限等 |
| AI 问答 | 基于当前论文原文；含 6 个快捷问题 |
| 导出 | 将阅读总结下载为 `.md` 文件 |
| 长文处理 | 自动截取开头 + 结尾，避免超出模型上下文 |

## 常见问题

| 现象 | 可能原因 |
|------|----------|
| 提示“未能提取到足够文字” | 扫描版/图片型 PDF，请换文字版 |
| 未配置 `OPENAI_API_KEY` | 请创建 `.env` 并填入有效密钥 |
| 提示「请求超时」 | 本机到 api.openai.com 网络不稳；调大 `OPENAI_TIMEOUT` 或设置 `HTTPS_PROXY` |
| 429 insufficient_quota | 该 Key 所属账户余额为 0，需到 OpenAI 后台充值 |
| 云端部署后提示未配置 Key | 未在平台 Secrets 中配置 `OPENAI_API_KEY` |
| `ModuleNotFoundError` | 未激活虚拟环境或未 `pip install -r requirements.txt` |
| 无法解析 PDF | 文件损坏、加密或非标准 PDF |
| 导出按钮不可用 | 需先成功完成「开始分析」 |

## 注意事项

- API Key 仅通过环境变量读取，切勿写入代码或提交仓库。  
- AI 输出可能不完整或不准确，请以论文原文为准。  
- 第一版不含数据库、登录、OCR、RAG。  
