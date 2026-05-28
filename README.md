# 智慧树考试自动化答题脚本

![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.40-2EAD33?style=flat-square&logo=playwright&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-F5A623?style=flat-square)

基于 Playwright 与通义千问大模型的智慧树平台考试自动答题工具。使用视觉模型 OCR 识别防复制题目，AI 分析作答，支持单选/多选/判断题。

---

## 功能特性

- 使用通义千问视觉大模型 OCR 识别题干，完美应对平台防复制及自定义混淆字体
- 选项中包含图片时自动捕获图片地址并传送给 AI 分析
- 支持单选题、多选题、判断题，多选重做时自动先取消已选选项
- 答完所有题目后自动点击"保存"但**不会自动提交**，留给用户核对确认
- 切换题目时智能等待题号完全更新，避免状态冲突
- 支持跳过已完成题目的选项配置
- 遇到滑块验证码时暂停程序，等待用户手动完成后自动继续
- 若系统未安装标准 Google Chrome，自动降级使用 Playwright 自带的 Chromium

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

> API 密钥可前往 [阿里云百炼控制台](https://bailian.console.aliyun.com/) 申请。所有请求走标准 OpenAI Chat Completions 接口，可将 `QWEN_ENDPOINT` 和 `QWEN_API_KEY` 替换为其他兼容服务（如 DeepSeek、硅基流动等）。

---

## 运行流程

1. 程序启动浏览器，自动填写账号密码登录智慧树
2. 登录时若出现滑块验证，控制台提示手动完成，完成后程序自动继续
3. 控制台要求输入考试页面的 URL 链接（如已在 `.env` 中配置 `EXAM_URL` 则自动跳过）
4. 逐题分析：截图 OCR 识别题干 → 调用 AI 分析 → 点击答案 → 切换下一题
5. 全卷答完后自动点击"保存"，**不会自动提交**
6. 用户人工核对确认后，手动点击"提交"

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
