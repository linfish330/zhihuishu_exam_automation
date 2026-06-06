# 智慧树考试自动化答题脚本

![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.40-2EAD33?style=flat-square&logo=playwright&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-F5A623?style=flat-square)

基于 Playwright 与通义千问大模型的智慧树平台考试自动答题工具。使用视觉模型 OCR 识别防复制题目，AI 分析并参考本地背景知识作答，支持单选/多选/判断/填空/简答等全题型。

---

## 功能特性

- **多题型支持**：支持单选题、多选题、判断题，以及填空题与简答题（自动识别空格数量，AI 以 JSON 结构化形式返回答案并自动填入网页）。
- **参考资料检索 (RAG)**：支持将本地参考资料（如课程笔记、课件、题库）放入指定文件夹，大模型会基于题目内容通过 TF-IDF 和中文 N-gram 算法自动检索最相关的文档作为背景上下文进行答题，显著提升作答准确率。
- **免复制 OCR 识别**：使用通义千问视觉大模型对题干进行截图 OCR 识别，完美应对平台防复制、乱码及自定义混淆字体。
- **选项图片识别**：当选项中包含图片时，自动捕获图片地址并发送给 AI 进行识别与分析。
- **安全防冲突机制**：切换题目时智能等待题号完全更新，避免状态冲突；多选重做时自动先清空已选选项。
- **多考试连续处理**：支持多场考试连续作答，每场考试结束后可选择继续下一场，支持直接输入链接或直接按下回车处理当前浏览器中手动打开的页面。
- **智能人机接管**：登录或答题时若遇到滑块验证码，程序会自动暂停并提示用户手动完成，完成后程序自动继续。
- **免安装 Chromium 兜底**：若系统未安装标准 Google Chrome，自动降级使用 Playwright 自带的 Chromium 浏览器。
- **自动保存不提交**：答完所有题目后自动点击"保存"但**不会自动提交**，安全稳妥，留给用户人工检查核对。

---

## 快速开始

> 需要 Python 3.10+ 环境。如未安装，请先前往 [Python 官网](https://www.python.org/downloads/) 下载安装。

```bash
# 1. 克隆项目
git clone https://github.com/LUOLIN926/zhihuishu_exam_automation.git
cd zhihuishu_exam_automation

# 2. 安装依赖
pip install -r requirements.txt
playwright install

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入账号密码和 API Key

# 4. 运行
python zhihuishu_exam_automation.py
```

---

## 配置说明

复制 `.env.example` 为 `.env`，按需修改以下参数：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `USERNAME` | 是 | 智慧树登录手机号 |
| `PASSWORD` | 是 | 智慧树登录密码 |
| `QWEN_API_KEY` | 是 | 阿里云百炼 API 密钥 |
| `QWEN_ENDPOINT` | 否 | API 端点，默认 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` |
| `ANSWER_MODEL` | 否 | 答题模型名称，默认 `qwen3.6-plus` |
| `OCR_MODEL` | 否 | OCR 识别的视觉模型，默认 `qwen3.6-plus` |
| `SKIP_COMPLETED_QUESTIONS` | 否 | 是否跳过已完成题目，默认 `true` |
| `ENABLE_REASONING` | 否 | 是否启用推理模式，默认 `false` |
| `EXAM_URL` | 否 | 指定考试链接（留空则运行时手动输入） |
| `REFERENCE_DIR` | 否 | 参考资料文件夹路径，默认为 `reference_materials` |
| `REFERENCE_MODE` | 否 | 参考资料导入模式：`rag` (基于题干与选项智能检索相关文档作为背景知识，推荐)、`full` (全部载入)、`none` (不导入背景知识) |
| `REFERENCE_TOP_K` | 否 | 当 `REFERENCE_MODE` 为 `rag` 时，检索返回的最相关文档数量，默认 `3` |

> API 密钥可前往 [阿里云百炼控制台](https://bailian.console.aliyun.com/) 申请。所有请求走标准 OpenAI Chat Completions 接口，可将 `QWEN_ENDPOINT` 和 `QWEN_API_KEY` 替换为其他兼容服务（如 DeepSeek、硅基流动等）。

---

## 参考资料功能（RAG）使用说明

为了大幅提高 AI 答题的准确率（尤其是专业性较强、题库中存在原题或有标准课件背景的考试），本项目支持**本地参考资料智能检索（RAG）**功能。

### 1. 准备参考资料
在项目根目录下创建参考资料文件夹（默认名称为 `reference_materials`）。
把该课程的相关资料放进去，支持的文件格式包括：
* **`.md`** (Markdown 格式，推荐)
* **`.txt`** (纯文本格式)

> **💡 提示**：你可以将复习资料、往年题库、PPT 导出的文本或者课程大纲按章节或知识点拆分成多个小文件放入。文件名最好具有描述性，如 `1.1_灰塑的起源.md`。

### 2. 检索原理与模式选择
程序在启动时会自动读取该目录下的所有文档并进行分词，采用 **TF-IDF** 权重算法建立轻量级本地倒排索引。在答题时，程序会执行以下流程：
1. 提取当前题目的题干和选项内容作为 Query。
2. 针对中文，程序会智能提取双字及三字组 N-gram 促进鲁棒的字词匹配；针对英文和数字，提取独立单词。
3. 计算匹配得分并提取最相关的 Top K 篇文档。
4. 将文档内容注入 Prompt 的 `参考资料` 区域，供 AI 决策作答。

你可以在 `.env` 中通过 `REFERENCE_MODE` 设置以下三种模式：
- **`rag`** (推荐/默认)：根据当前题目智能搜索最相关的 Top K 篇文档作为上下文。这样既能提供精准参考，又不会导致 API Token 超出模型上下文限制或产生高额费用。
- **`full`**：不经过筛选，直接将该目录下所有文件的全部内容拼接并作为上下文发送给 AI。适用于资料库极小（总字数在数千字以内）的情况。
- **`none`**：关闭参考资料功能，仅依赖大模型自身的通用知识答题。

---

## 运行流程

1. 程序启动浏览器，加载 `reference_materials` 中的参考资料，并完成倒排索引建立。
2. 自动填写账号密码登录智慧树，如果登录出现滑块验证，程序会提示人机接管。
3. 自动跳转或手动进入考试：
   - 若 `.env` 中配置了 `EXAM_URL`，自动跳转至指定考试。
   - 若未配置，控制台会提示用户输入考试 URL，或直接回车开始处理当前页面上手动打开的考试。
4. 逐题分析作答：
   - 题干截图与百炼大模型 VLM (如 qwen3.6-plus) OCR 识别。
   - 提取题目类型、题目选项（含图片 URL）。
   - **参考资料检索**：根据题干和选项，在本地参考资料中执行 TF-IDF + N-gram 智能检索，获取最相关的知识背景。
   - **大模型决策**：将识别出的题目、选项以及检索到的参考背景知识整合成 Prompt 发送给大模型。
   - **自动填写**：对于选择/判断题自动点击对应选项（多选题支持重做时自动清空历史选中选项）；对于填空/简答题，智能识别空格数并自动回填 AI 结构化输出。
   - **智能更新检测**：自动等待题号完成切换，防状态冲突，随后处理下一题。
5. 全卷作答完毕后，程序自动点击网页上的“保存”按钮（最后一题），但**不会自动提交**。
6. 控制台询问是否需要处理下一门考试：
   - 输入 `y` 即可再次进入等待输入或手动打开的状态，实现一键处理多科目的连续答题。
   - 输入其他内容即可退出程序，浏览器保持开启供用户人工检查并手动提交。

---

## 技术栈

| 类别 | 技术 | 版本 |
| --- | --- | --- |
| 语言 | Python | 3.10+ |
| 浏览器自动化 | Playwright | 1.40.0 |
| LLM API | 阿里云 DashScope（通义千问） | OpenAI 兼容接口 |
| HTTP 客户端 | httpx | 0.25.2 |
| 图像处理 | Pillow, OpenCV, pytesseract | 截图与 OCR 辅助 |
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
