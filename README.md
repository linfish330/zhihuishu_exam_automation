# 智慧树考试自动化答题与课程知识库下载工具

![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.40-2EAD33?style=flat-square&logo=playwright&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-F5A623?style=flat-square)

基于 Playwright、通义千问大模型与语音转写 API 的智慧树平台学习与答题自动化工具。包含两个独立的脚本：一个负责批量下载课程视频并自动转写为本地 Markdown 知识库，另一个负责在考试时基于该本地知识库进行 RAG（检索增强生成）高准确度答题。

---

## 功能特性

- **两个脚本独立运行**：视频下载转写工具 (`zhihuishu_video_downloader.py`) 与考试自动答题工具 (`zhihuishu_exam_automation.py`) 相互独立，各司其职。
- **三路并行搜索机制**（核心升级）：
  1. **本地 RAG 检索**：自动递归匹配本地课程知识库与课件资料。
  2. **脚本联网搜索**：自动提取题干执行搜索引擎关键词检索，获取最新网页摘要。
  3. **模型自带检索**：大模型端 `enable_search` 实时联网。
  三路信息完美融合，提供多重参考，答题准确率大幅跃升。
- **本地知识库自动生成**：下载课程视频后，自动将视频音频分离并使用语音识别 (ASR) 转写为 Markdown 格式的文稿。
- **多题型支持**：支持单选题、多选题、判断题，以及填空题与简答题（自动识别空格数量，AI 结构化返回并自动填入网页）。
- **免复制 OCR 识别**：使用通义千问视觉大模型对题干进行截图 OCR 识别，完美应对平台防复制、乱码及混淆字体。
- **智能人机接管**：登录或答题时若遇到滑块验证码，程序会自动暂停并提示用户手动完成，完成后程序自动继续。
- **自动保存不提交**：答题结束后自动保存答案，但**绝对不会自动提交**，留给用户人工检查核对。

---

## 快速开始

> **运行环境要求**：Python 3.10+。如未安装，请前往 [Python 官网](https://www.python.org/downloads/) 下载安装。另外，转写功能依赖系统级 `ffmpeg`，请确保系统已安装 `ffmpeg` 并已将其添加至系统环境变量。

### 1. 克隆项目与安装依赖
```bash
# 1. 克隆项目
git clone https://github.com/LUOLIN926/zhihuishu_exam_automation.git
cd zhihuishu_exam_automation

# 2. 安装依赖与浏览器内核
pip install -r requirements.txt
playwright install
```

### 2. 配置环境变量
复制 `.env.example` 为 `.env`：
```bash
cp .env.example .env
```
用编辑器打开 `.env` 文件，填入您的**智慧树账号密码**、**答题 API 密钥（QWEN_API_KEY）**，以及**转写 API 密钥（MIMO_API_KEY）**。

---

## 核心工作流：先下载知识库，后自动答题 💡

为了取得最佳的答题准确率，请务必遵循以下“**两步走**”的流程：

### 第一步：下载并转写课程视频，生成本地知识库
运行视频下载与转写脚本。它会自动模拟登录，进入您指定的课程，提取视频并在本地并发下载。下载完成后，它会自动调用 MiMo 语音转写 API，将视频中的语音转写为 Markdown 格式的文稿，并直接保存在项目根目录下的 `reference_materials/<课程名称>/` 目录中。

```bash
# 运行视频下载与转写工具
python zhihuishu_video_downloader.py
```
> **提示**：转写完成后，原视频文件会被自动删除以节省本地磁盘空间，仅保留转写好的 `.md` 本地知识库。

### 第二步：运行答题脚本，基于知识库进行智能考试作答
启动考试自动化脚本。它在启动时会**自动递归扫描**整个 `./reference_materials` 文件夹中的所有 Markdown 知识库。当它识别到考试题目时，会智能检索最相关的视频文稿作为背景知识，辅助 AI 完美答题。

```bash
# 运行考试自动化答题脚本
python zhihuishu_exam_automation.py
```

---

## 配置说明

按需在 `.env` 中修改以下参数：

| 类别 | 变量 | 必填 | 说明 |
| --- | --- | --- | --- |
| **通用账号** | `ZHIHUISHU_USERNAME` | 是 | 智慧树登录手机号 |
| | `ZHIHUISHU_PASSWORD` | 是 | 智慧树登录密码 |
| **视频下载器** | `COURSE_NAME` | 是 | 要下载并生成知识库的课程完整名称（例如 `"形势与政策"`） |
| | `DOWNLOAD_DIR` | 否 | 视频临时保存目录，默认 `./videos` |
| | `QUALITY` | 否 | 视频画质：`high`（高清原画）或 `low`（标清，默认） |
| | `CONCURRENT` | 否 | 视频并发下载数，默认 `3` |
| **语音转写** | `MIMO_API_KEY` | 否 | [MiMo 语音转写 API 密钥](https://api.xiaomimimo.com/)，用于转录视频生成知识库 |
| | `MIMO_BASE_URL` | 否 | 转写 API 地址，默认 `https://api.xiaomimimo.com/v1` |
| | `MIMO_MODEL` | 否 | 转写模型名称，默认 `mimo-v2.5-asr` |
| **考试答题** | `QWEN_API_KEY` | 是 | 阿里云百炼/OpenAI 兼容的大模型 API 密钥 |
| | `QWEN_ENDPOINT` | 否 | 大模型 API 端点，默认通义千问端点 |
| | `ANSWER_MODEL` | 否 | 答题大模型，推荐使用 `qwen3.6-plus` |
| | `OCR_MODEL` | 否 | 题目 OCR 视觉大模型，默认 `qwen3.6-plus` |
| **参考检索** | `REFERENCE_DIR` | 否 | 参考资料/知识库总文件夹路径，默认为 `reference_materials` |
| | `REFERENCE_MODE` | 否 | 参考资料检索模式：`rag`（基于题干智能检索，推荐）、`full`（全部导入）、`none`（不导入） |
| | `REFERENCE_TOP_K` | 否 | RAG 检索返回的相关文档数量上限，默认 `3` |
| | `ENABLE_KEYWORD_SEARCH`| 否 | 是否启用脚本端联网关键词网页搜索（自动提取题干并通过搜索引擎获取参考信息），默认 `true` |
| **答题控制** | `SKIP_COMPLETED_QUESTIONS`| 否 | 是否跳过已经做完的题目，默认 `true` |
| | `ENABLE_REASONING` | 否 | 是否启用大模型推理模式，默认 `false` |
| | `EXAM_URL` | 否 | 指定直接跳转的考试 URL（为空则运行时手动输入或直接回车解析当前页面） |

---

## 参考资料与联网检索（RAG & Search）说明

为了确保 AI 作答的极致准确性，本项目构建了**三路并行**的信息检索体系：

### 1. 本地参考资料 RAG 检索
程序在启动时，会**自动递归遍历** `reference_materials` 目录。
* **支持多课程隔离**：程序将以文件相对路径（如 `reference_materials/形势与政策/1.1 导言.md`）作为文档唯一标识，防止键值碰撞。
* **分词检索**：答题时，程序会提取题目题干和选项作为检索 Query，通过 TF-IDF 算法匹配出最相关的 Top K 个知识分片。

### 2. 脚本端联网关键词搜索
为了防止大模型自带的联网搜索失效或因地域限制无法获取特定题目答案，脚本在调用 API 前，会：
* 自动提取干净题干（移除题号、题型前缀、无关括号等干扰字符）。
* 优先使用 **DuckDuckGo HTML 引擎**，国内无 VPN 环境下自动无缝降级至 **360 搜索 (so.com)** 引擎。
* 检索网页并将前 3 条搜索结果标题与网页摘要以 `【联网网页搜索结果】` 格式实时注入到 Prompt 提示词中。

### 3. 模型侧内置联网搜索
在调用大模型时，通过传入 `"enable_search": True`，让大模型本身在生成答案时也能调用模型厂商的内置网页检索能力，与脚本端搜索和本地 RAG 形成交叉双重校验。

---

## 运行流程

1. **第一步（准备知识库）**：用户通过 `.env` 配置课程名和 API，运行 `python zhihuishu_video_downloader.py` 下载视频并自动完成音频分离、ASR 切片转写，生成对应课程的本地 Markdown 知识库至 `reference_materials/<课程名>/`。
2. **第二步（执行答题）**：运行 `python zhihuishu_exam_automation.py`。
3. 程序自动递归扫描并合并索引 `reference_materials` 目录下的所有参考文档。
4. 自动打开 Chrome 浏览器，模拟填写账号密码登录智慧树，遇验证码时由用户接管手动验证。
5. 登录成功后，程序检测到指定的 `EXAM_URL` 或等待用户手动输入并回车开始答题。
6. 逐题作答流程：
   - 题干截图，AI 视觉模型 (VLM) 自动 OCR 提取防复制内容。
   - 提取选项类型（单选/多选/判断/填空等）及选项内容。
   - **RAG 匹配**：利用提取的内容在合并的本地知识库中进行 TF-IDF 检索，找到最匹配的前 K 个文件分片。
   - **联网关键词检索**：自动调用搜索引擎获取与题干最相关的网页摘要。
   - **大模型答题**：将匹配的本地上下文、网页检索摘要、题干与选项发送给大模型获取答案。
   - **自动点击/填入**：多选题自动清除重做，填空与简答题识别出空格数量后自动回填。
   - **状态轮询**：检测到题号跳转更新后继续下一题。
7. 最后一题处理完后，自动点击“保存”，提示用户进行人工最终核对。支持交互式直接继续处理下一科考试。

---

## 技术栈

| 类别 | 技术 | 版本 |
| --- | --- | --- |
| 语言 | Python | 3.10+ |
| 浏览器自动化 | Playwright | 1.40.0 |
| LLM API | 阿里云 DashScope（通义千问） | OpenAI 兼容接口 |
| HTTP 客户端 | httpx | 0.27.0 |
| 网页解析 | BeautifulSoup4 | 用于提取搜索引擎网页摘要 |
| 图像处理 | Pillow | 网页截图辅助 |
| 配置管理 | python-dotenv | 1.0.0 |

---

## 常见问题

**Q: 运行提示 `'python' 不是内部或外部命令`**
安装 Python 时务必勾选 `Add Python to PATH`，或卸载重装。

**Q: 提示 `ModuleNotFoundError: No module named 'playwright'`**
在项目目录下重新运行 `pip install -r requirements.txt`。如不行，尝试 `pip3`。

**Q: 启动时报错 `Executable ... not found`**
运行 `playwright install` 下载浏览器内核。

**Q: API 调用失败**
检查 `.env` 中的 API Key 是否正确；登录 [阿里云百炼控制台](https://bailian.console.aliyun.com/) 检查余额。

**Q: 智慧树页面改版导致脚本失效**
到 [GitHub Issues](https://github.com/LUOLIN926/zhihuishu_exam_automation/issues) 反馈。

**Q: 如何使用其他模型**
修改 `.env` 中的 `QWEN_ENDPOINT` 和 `QWEN_API_KEY` 为对应服务的地址和密钥即可。

**Q: 程序会自动提交试卷吗？**
不会。程序只自动保存答案，最终提交需要用户手动确认。

---

## 免责声明

本项目仅供学习与技术交流使用，请勿用于商业用途。使用自动化工具可能会违反平台协议，所带来的后果由使用者自行承担。AI 模型的回答可能存在不准确性，成绩风险由使用者自负。
