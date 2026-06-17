import asyncio
import json
import re
import time
import math
from datetime import datetime
import httpx
from playwright.async_api import async_playwright
from dotenv import load_dotenv, dotenv_values
import os
import logging
import base64

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

load_dotenv()

class ReferenceManager:
    def __init__(self, dir_path=None):
        self.dir_paths = []
        env_dir = dir_path or os.getenv("REFERENCE_DIR", "reference_materials")
        if env_dir:
            self.dir_paths.append(env_dir)
        
        # 自动将根目录下的 "markdown" 目录也纳入扫描范围（若存在且未在列表中）
        if os.path.exists("markdown") and "markdown" not in self.dir_paths:
            self.dir_paths.append("markdown")
            
        self.docs = {}          # filepath_key -> file content
        self.doc_words = {}     # filepath_key -> set of tokens
        self.idf = {}           # token -> idf score
        self.full_context = ""  # concatenated text of all files (for 'full' mode)
        self.load_documents()

    def tokenize(self, text):
        if not text:
            return set()
        text = text.lower()
        # 寻找中文字符
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]', text)
        # 寻找英文单词和数字
        english_words = re.findall(r'[a-zA-Z0-9]+', text)
        
        tokens = set(english_words)
        # 生成中文双字与三字组 N-gram 促进鲁棒的中文搜索
        for i in range(len(chinese_chars) - 1):
            tokens.add(chinese_chars[i] + chinese_chars[i+1])
        for i in range(len(chinese_chars) - 2):
            tokens.add(chinese_chars[i] + chinese_chars[i+1] + chinese_chars[i+2])
            
        return tokens

    def load_documents(self):
        all_tokens = []
        full_texts = []
        loaded_filepaths = set()
        
        for dir_path in self.dir_paths:
            if not os.path.exists(dir_path):
                continue
            
            logger.info(f"正在扫描参考资料目录: {dir_path}")
            
            try:
                # 递归遍历目录
                for root, dirs, files in os.walk(dir_path):
                    files.sort()
                    for filename in files:
                        if filename.endswith('.md') or filename.endswith('.txt'):
                            filepath = os.path.abspath(os.path.join(root, filename))
                            if filepath in loaded_filepaths:
                                continue
                            
                            # 使用相对于当前工作目录的路径作为唯一的文档 Key，避免重名冲突并在日志中清晰展示
                            rel_path = os.path.relpath(filepath, os.getcwd())
                            
                            try:
                                with open(filepath, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                self.docs[rel_path] = content
                                tokens = self.tokenize(content)
                                self.doc_words[rel_path] = tokens
                                all_tokens.append(tokens)
                                full_texts.append(f"【参考资料：{rel_path}】\n{content}\n")
                                loaded_filepaths.add(filepath)
                            except Exception as e:
                                logger.warning(f"读取参考文件失败 {rel_path}: {e}")
            except Exception as e:
                logger.error(f"加载参考资料目录 {dir_path} 时发生错误: {e}")
                
        self.full_context = "\n".join(full_texts)
        
        # 计算 IDF
        num_docs = len(self.docs)
        if num_docs == 0:
            logger.warning(f"所有扫描的参考资料目录 {self.dir_paths} 中均未发现符合条件的 .md 或 .txt 文件")
            return
            
        df = {}
        for tokens in all_tokens:
            for token in tokens:
                df[token] = df.get(token, 0) + 1
                
        for token, count in df.items():
            # 平滑的 IDF 公式
            self.idf[token] = math.log((num_docs + 1) / (count + 0.5))
            
        logger.info(f"成功加载并索引了 {num_docs} 篇参考资料。总字符数: {len(self.full_context)}")

    def search(self, query, top_k=3):
        if not self.docs:
            return []
            
        query_tokens = self.tokenize(query)
        scores = {}
        for filename, doc_tokens in self.doc_words.items():
            score = 0
            for token in query_tokens:
                if token in doc_tokens:
                    score += self.idf.get(token, 1.0)
            if score > 0:
                scores[filename] = score
                
        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_docs[:top_k]

    def get_context(self, query=None):
        mode = os.getenv("REFERENCE_MODE", "rag").lower()
        if mode == "none":
            return ""
        elif mode == "full":
            return self.full_context
        elif mode == "rag":
            if not query:
                return ""
            top_k = int(os.getenv("REFERENCE_TOP_K", "3"))
            results = self.search(query, top_k=top_k)
            if not results:
                logger.info("RAG 检索未匹配到任何相关参考资料")
                return ""
            
            logger.info(f"RAG 检索完成，匹配到相关文档: {[r[0] for r in results]}")
            retrieved_texts = []
            for filename, score in results:
                retrieved_texts.append(f"【参考资料：{filename} (相关度评分: {score:.2f})】\n{self.docs[filename]}")
            return "\n\n".join(retrieved_texts)
        else:
            logger.warning(f"未知的 REFERENCE_MODE: {mode}，默认不加载参考资料")
            return ""


def _clean_thinking_process(text):
    """移除大模型可能返回的思考过程（如 <think>...</think> 或 [thinking]... 等标记）"""
    if not text:
        return ""
    import re
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[thinking\].*?\[/thinking\]', '', text, flags=re.DOTALL)
    return text.strip()

async def async_input(prompt_msg: str = "") -> str:
    """异步读取用户输入，避免阻塞 asyncio 事件循环"""
    return await asyncio.get_event_loop().run_in_executor(None, input, prompt_msg)

def clean_search_query(text: str) -> str:
    if not text:
        return ""
    # 移除题型前缀如 【单选题】 或 [多选题]
    text = re.sub(r'[【\[](?:单选|多选|判断|填空|简答)题?[】\]]', '', text)
    # 移除题号如 1. 或 第1题：或 1、
    text = re.sub(r'^\s*(?:第\s*\d+\s*[题.、\s]|\d+\s*[.、\s])\s*', '', text)
    # 移除尾部括号、下划线及空格
    text = re.sub(r'[\s（(_下划线_]*[）)]*\s*$', '', text)
    return text.strip()

async def perform_web_search(query: str, top_k: int = 3) -> str:
    """联网关键词搜索：优先使用 DuckDuckGo，如失败则回退至 360 搜索"""
    if not query:
        return ""
        
    import urllib.parse
    from bs4 import BeautifulSoup
    
    cleaned_query = clean_search_query(query)
    if not cleaned_query:
        cleaned_query = query
        
    logger.info(f"正在执行联网关键词搜索: '{cleaned_query}'")
    
    # 1. 尝试使用 DuckDuckGo
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(cleaned_query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                results = []
                for result in soup.find_all('div', class_='result'):
                    title_el = result.find('a', class_='result__a')
                    snippet_el = result.find('a', class_='result__snippet')
                    if title_el and snippet_el:
                        results.append({
                            'title': title_el.get_text(strip=True),
                            'snippet': snippet_el.get_text(strip=True),
                            'link': title_el.get('href', '')
                        })
                if results:
                    logger.info(f"DuckDuckGo 检索到 {len(results)} 条结果，取前 {top_k} 条")
                    formatted_results = []
                    for i, res in enumerate(results[:top_k]):
                        formatted_results.append(f"【网页搜索结果 {i+1}】\n标题: {res['title']}\n摘要: {res['snippet']}\n链接: {res['link']}")
                    return "\n\n".join(formatted_results)
    except Exception as e:
        logger.warning(f"DuckDuckGo 搜索失败: {e}，将尝试 360 搜索...")
        
    # 2. 尝试使用 360 搜索
    try:
        url = f"https://www.so.com/s?q={urllib.parse.quote(cleaned_query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                results = []
                for item in soup.find_all('li', class_='res-list'):
                    h3 = item.find('h3')
                    snippet_el = item.find(class_='res-list-summary') or item.find(class_='res-desc') or item.find('p')
                    if h3 and snippet_el:
                        title = h3.get_text(strip=True)
                        link = h3.find('a').get('href', '') if h3.find('a') else ''
                        snippet = snippet_el.get_text(strip=True)
                        results.append({
                            'title': title,
                            'snippet': snippet,
                            'link': link
                        })
                if results:
                    logger.info(f"360 搜索检索到 {len(results)} 条结果，取前 {top_k} 条")
                    formatted_results = []
                    for i, res in enumerate(results[:top_k]):
                        formatted_results.append(f"【网页搜索结果 {i+1}】\n标题: {res['title']}\n摘要: {res['snippet']}\n链接: {res['link']}")
                    return "\n\n".join(formatted_results)
    except Exception as e:
        logger.warning(f"360 搜索也失败: {e}")
        
    logger.info("未检索到任何联网关键词搜索结果")
    return ""

async def check_and_handle_captcha(page):
    """检测验证码弹窗；出现时提示人工处理并等待消失。"""
    try:
        yidun_modal = await page.query_selector('div.yidun_modal')
        if yidun_modal and await yidun_modal.is_visible():
            logger.info("检测到验证码弹窗，等待用户处理...")
            print("【请接管】请手动完成弹窗验证码输入")
            
            try:
                await page.wait_for_selector('div.yidun_modal', state='hidden', timeout=600000)
                logger.info("验证码处理完成，继续")
                return True
            except Exception as wait_error:
                logger.warning(f"等待验证码结束时出错或超时: {wait_error}")
                return True
        return False
    except Exception as e:
        logger.warning(f"检测验证码弹窗时出现错误: {e}")
        return False

async def wait_for_question_number(page, target_num, timeout=5):
    """等待页面上的题号变为目标题号。"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            num_element = await page.query_selector('div.subject_num.fl span')
            if num_element:
                current_num_text = await num_element.inner_text()
                import re
                num_match = re.search(r'(\d+)', current_num_text)
                if num_match and int(num_match.group(1)) == target_num:
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.2)
    return False


async def ai_answer_question(page, question_num, total_questions, reference_manager=None):
    """处理单题：提取题干与选项，调用模型作答并推进到下一题。"""
    
    logger.info(f"开始处理第 {question_num} 题")
    await check_and_handle_captcha(page)
    
    skip_completed_questions = os.getenv('SKIP_COMPLETED_QUESTIONS', 'true').lower() == 'true'
    
    subject_containers = await page.query_selector_all('div.examPaper_subject')
    if not subject_containers:
        logger.error("未找到任何题目容器")
        return
    
    current_subject = None
    current_question_num = 0
    for i, container in enumerate(subject_containers):
        is_visible = await container.is_visible()
        if is_visible:
            current_subject = container
            try:
                num_element = await container.query_selector('div.subject_num.fl span')
                if num_element:
                    current_num_text = await num_element.inner_text()
                    import re
                    num_match = re.search(r'(\d+)', current_num_text)
                    if num_match:
                        current_question_num = int(num_match.group(1))
                        logger.info(f"当前题目序号: {current_question_num}")
                    else:
                        logger.warning(f"无法从 '{current_num_text}' 中提取数字")
                        current_question_num = 0
                else:
                    logger.warning("未找到题目序号元素")
                    current_question_num = 0
            except Exception as e:
                logger.warning(f"获取题目序号时出错: {e}")
                current_question_num = 0
            break
    
    if current_question_num != question_num:
        logger.warning(f"开始处理第 {question_num} 题，但当前页面显示第 {current_question_num} 题，启动纠错机制")
        
        await asyncio.sleep(3)
        subject_containers = await page.query_selector_all('div.examPaper_subject')
        current_subject = None
        current_question_num = 0
        
        for i, container in enumerate(subject_containers):
            is_visible = await container.is_visible()
            if is_visible:
                current_subject = container
                try:
                    num_element = await container.query_selector('div.subject_num.fl span')
                    if num_element:
                        current_num_text = await num_element.inner_text()
                        num_match = re.search(r'(\d+)', current_num_text)
                        if num_match:
                            current_question_num = int(num_match.group(1))
                            logger.info(f"重检当前题目序号: {current_question_num}")
                        else:
                            logger.warning(f"重检时无法从 '{current_num_text}' 中提取数字")
                            current_question_num = 0
                    else:
                        logger.warning("重检时未找到题目序号元素")
                        current_question_num = 0
                except Exception as e:
                    logger.warning(f"重检时获取题目序号出错: {e}")
                    current_question_num = 0
                break
        
        if current_question_num == question_num:
            logger.info(f"重检后题目序号一致，开始处理第 {current_question_num} 题")
        else:
            logger.info(f"重检后仍不一致，当前页面显示第 {current_question_num} 题，需要处理第 {question_num} 题，点击下一题")
            
            next_button = await page.query_selector('button:has-text("下一题")')
            if next_button:
                await next_button.click()
                logger.info("已点击下一题按钮")
            else:
                logger.warning("未找到下一题按钮")
            
            await asyncio.sleep(1)
            subject_containers = await page.query_selector_all('div.examPaper_subject')
            current_subject = None
            current_question_num = 0
            
            for i, container in enumerate(subject_containers):
                is_visible = await container.is_visible()
                if is_visible:
                    current_subject = container
                    try:
                        num_element = await container.query_selector('div.subject_num.fl span')
                        if num_element:
                            current_num_text = await num_element.inner_text()
                            num_match = re.search(r'(\d+)', current_num_text)
                            if num_match:
                                current_question_num = int(num_match.group(1))
                                logger.info(f"点击下一题后当前题目序号: {current_question_num}")
                            else:
                                logger.warning(f"点击下一题后无法从 '{current_num_text}' 中提取数字")
                                current_question_num = 0
                        else:
                            logger.warning("点击下一题后未找到题目序号元素")
                            current_question_num = 0
                    except Exception as e:
                        logger.warning(f"点击下一题后获取题目序号出错: {e}")
                        current_question_num = 0
                    break
        
        if current_question_num != question_num:
            logger.error(f"纠错后仍不一致，当前页面显示第 {current_question_num} 题，需要处理第 {question_num} 题")
            print("【暂停答题】题目序号不一致，请手动处理到正确题目后按回车键继续...")
            await async_input()
            logger.info("用户已确认，继续答题")
            
            subject_containers = await page.query_selector_all('div.examPaper_subject')
            current_subject = None
            current_question_num = 0
            
            for i, container in enumerate(subject_containers):
                is_visible = await container.is_visible()
                if is_visible:
                    current_subject = container
                    try:
                        num_element = await container.query_selector('div.subject_num.fl span')
                        if num_element:
                            current_num_text = await num_element.inner_text()
                            num_match = re.search(r'(\d+)', current_num_text)
                            if num_match:
                                current_question_num = int(num_match.group(1))
                                logger.info(f"用户处理后当前题目序号: {current_question_num}")
                            else:
                                logger.warning(f"用户处理后无法从 '{current_num_text}' 中提取数字")
                                current_question_num = 0
                        else:
                            logger.warning("用户处理后未找到题目序号元素")
                            current_question_num = 0
                    except Exception as e:
                        logger.warning(f"用户处理后获取题目序号出错: {e}")
                        current_question_num = 0
                    break

    if not current_subject:
        logger.error("未找到当前显示的题目")
        return
    
    subject_type_elements = await current_subject.query_selector_all('div.subject_type_annex span')
    subject_type = "未知题型"
    if subject_type_elements:
        for i, element in enumerate(subject_type_elements):
            text = await element.inner_text()
            if text and ('单选' in text or '多选' in text or '判断' in text or '填空' in text or '简答' in text):
                subject_type = text
                logger.info(f"当前题目类型: {subject_type}")
                break
    else:
        logger.warning("未找到任何题型信息")
    
    is_fill_blank = '填空' in subject_type or '简答' in subject_type

    # 检测并提取填空题/简答题的输入框
    blank_elements = []
    if is_fill_blank:
        blank_elements = await current_subject.query_selector_all('textarea.text_textarea')
        if not blank_elements:
            blank_elements = await current_subject.query_selector_all('textarea')
        if not blank_elements:
            blank_elements = await current_subject.query_selector_all('input[type="text"]')
        logger.info(f"检测到填空题，空格数: {len(blank_elements)}")

    is_question_completed = False
    if is_fill_blank:
        # 如果是填空题，检查是否所有格子都已有内容
        if blank_elements:
            filled_count = 0
            for elem in blank_elements:
                val = await elem.input_value()
                if val.strip():
                    filled_count += 1
            if len(blank_elements) > 0 and filled_count == len(blank_elements):
                is_question_completed = True
                logger.info(f"检测到第 {question_num} 题 (填空/简答题) 所有空格已填入内容")
    else:
        completed_indicators = await current_subject.query_selector_all('span.onChecked')
        if len(completed_indicators) > 0:
            is_question_completed = True
            logger.info(f"检测到第 {question_num} 题已完成")
    
    if is_question_completed:
        if skip_completed_questions:
            logger.info(f"题目已完成且设置为跳过，切换到下一题")
            next_button = await page.query_selector('button:has-text("下一题")')
            if next_button:
                await next_button.click()
                logger.info("已点击下一题按钮")
            else:
                logger.warning("未找到下一题按钮")
            return
        else:
            logger.info(f"题目已完成但设置为重做，继续处理")
    
    subject_describe = await get_subject_description_by_vl_ocr(page)
    
    options = []
    option_elements = []
    if not is_fill_blank:
        try:
            option_elements = await current_subject.query_selector_all('div.nodeLab')
            
            for i, element in enumerate(option_elements):
                letter_element = await element.query_selector('span.mr10, span.ABCase, span.onChecked')
                letter_text = ""
                if letter_element:
                    letter_text = await letter_element.inner_text()
                    letter_match = re.search(r'[A-Z]', letter_text)
                    if letter_match:
                        letter_text = letter_match.group(0)
                    
                content_element = await element.query_selector('div.node_detail p, div.node_detail span, div.node_detail.examquestions-answer')
                content_text = ""
                if content_element:
                    content_text = await content_element.inner_text()
                else:
                    content_element = await element.query_selector('div.label div.node_detail')
                    if content_element:
                        content_text = await content_element.inner_text()
                
                # 检测图片选项作为内容兜底
                if not content_text.strip():
                    img_element = await element.query_selector('img')
                    if img_element:
                        img_src = await img_element.get_attribute('src')
                        content_text = f"[图片] (URL: {img_src})"
                
                if letter_text and content_text:
                    options.append((letter_text, content_text, i, i+1))
                else:
                    logger.warning(f"无法提取选项 {i+1} 的字母或内容，尝试备用方法")
                    
                    label_element = await element.query_selector('div.label')
                    if label_element:
                        full_label_text = await label_element.inner_text()
                        letter_match = re.search(r'^\s*([A-Z])\.', full_label_text)
                        if letter_match:
                            letter_text = letter_match.group(1)
                            content_match = re.search(r'^\s*[A-Z]\.\s*(.+)', full_label_text)
                            if content_match:
                                content_text = content_match.group(1).strip()
                    
                    if not content_text.strip() and element:
                        img_element = await element.query_selector('img')
                        if img_element:
                            img_src = await img_element.get_attribute('src')
                            content_text = f"[图片] (URL: {img_src})"
    
                    if letter_text and content_text:
                        options.append((letter_text, content_text, i, i+1))
                    else:
                        logger.error(f"无法提取选项 {i+1} 的内容: {element}")
                        # 使用兜底，不直接抛出异常崩溃
                        letter_text = letter_text or chr(ord('A') + i)
                        content_text = content_text or f"[未知选项内容 {i+1}]"
                        options.append((letter_text, content_text, i, i+1))
        except Exception as e:
            logger.error(f"获取选项时出错: {e}")
            raise Exception(f"无法获取题目选项: {e}")
        
        if not options:
            logger.error("无法获取题目选项")
            raise Exception("无法获取题目选项")
    
    # 构建参考资料检索的查询词（题干 + 所有选项内容）
    ref_query = subject_describe
    if not is_fill_blank:
        for letter, content, index, number_index in options:
            ref_query += f" {content}"
        
    ref_context = ""
    if reference_manager:
        ref_context = reference_manager.get_context(ref_query)
        
    web_context = ""
    if os.getenv("ENABLE_KEYWORD_SEARCH", "true").lower() == "true":
        try:
            # 使用最简题干进行联网搜索
            web_context = await perform_web_search(subject_describe)
        except Exception as search_err:
            logger.warning(f"联网检索时发生异常: {search_err}")
            
    # 合并本地 RAG 资料和联网关键词搜索结果
    context_parts = []
    if ref_context:
        context_parts.append(f"【本地参考资料】\n{ref_context}")
    if web_context:
        context_parts.append(f"【联网网页搜索结果】\n{web_context}")
        
    context_str = "\n\n".join(context_parts)
        
    if is_fill_blank:
        num_blanks = len(blank_elements)
        if context_str:
            prompt = f"""
            参考背景知识：
            {context_str}

            请根据以上参考背景知识以及给出的填空/简答题题目，给出各空格的答案。
            本题共有 {num_blanks} 个填空/输入框。
            请直接返回一个 JSON 数组，包含 {num_blanks} 个字符串元素，分别对应各个空格的答案。
            不要返回任何其他解释、前缀、后缀或 Markdown 代码块标记（如 ```json 等）。只返回合法的 JSON 数组本身。

            示例（若有 2 个空格，答案分别是“北京”和“上海”，则只需返回）：
            ["北京", "上海"]

            示例（若只有 1 个输入框，答案是“中国”，则只需返回）：
            ["中国"]

            题目类型: {subject_type}
            题目描述: {subject_describe}
            """
        else:
            prompt = f"""
            请根据给出的填空/简答题题目，给出各空格的答案.
            本题共有 {num_blanks} 个填空/输入框。
            请直接返回一个 JSON 数组，包含 {num_blanks} 个字符串元素，分别对应各个空格的答案。
            不要返回任何其他解释、前缀、后缀或 Markdown 代码块标记（如 ```json 等）。只返回合法的 JSON 数组本身。

            示例（若有 2 个空格，答案分别是“北京”和“上海”，则只需返回）：
            ["北京", "上海"]

            示例（若只有 1 个输入框，答案是“中国”，则只需返回）：
            ["中国"]

            题目类型: {subject_type}
            题目描述: {subject_describe}
            """
    else:
        if context_str:
            prompt = f"""
            参考背景知识：
            {context_str}
    
            请根据以上参考背景知识以及给出的考试题目和选项，选择正确答案。请只返回选项的数字索引，不要返回其他内容。
            对于单选题，返回一个数字（如1）。对于多选题，返回多个数字，用分号分隔（如1;3;4）。
    
            题目类型: {subject_type}
            题目描述: {subject_describe}
            
            选项:
            """
        else:
            prompt = f"""
            请根据以下考试题目和选项，选择正确答案。请只返回选项的数字索引，不要返回其他内容。
            对于单选题，返回一个数字（如1）。对于多选题，返回多个数字，用分号分隔（如1;3;4）。
    
            题目类型: {subject_type}
            题目描述: {subject_describe}
            
            选项:
            """
        
        for letter, content, index, number_index in options:
            prompt += f"{number_index}. {letter}. {content}\n"
    
    if logger.level <= logging.DEBUG:
        logger.info(f"发送给大模型的提示词: \n{prompt}")
    
    api_key = os.getenv('QWEN_API_KEY')
    if not api_key:
        logger.error("未找到QWEN_API_KEY环境变量")
        return
    
    model_name = os.getenv('ANSWER_MODEL', os.getenv('MODEL_NAME', 'qwen3.6-plus'))
    logger.info(f"调用大模型API，模型: {model_name}")
    
    enable_reasoning = os.getenv('ENABLE_REASONING', 'False').lower() == 'true'
    
    base_endpoint = os.getenv('QWEN_ENDPOINT') or os.getenv('BASE_URL') or os.getenv('DASHSCOPE_BASE_URL') or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if "/chat/completions" in base_endpoint:
        url = base_endpoint
    else:
        url = f"{base_endpoint.rstrip('/')}/chat/completions"
    
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "extra_body": {
            "enable_search": True,
            "enable_thinking": enable_reasoning
        }
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            answer_text = result['choices'][0]['message']['content']
            logger.info(f"大模型返回的答案: {answer_text}")
            answer_text = _clean_thinking_process(answer_text)
            
            if is_fill_blank:
                # 尝试解析 JSON 数组
                answers = []
                cleaned_text = answer_text
                # 移除 markdown 代码块标记
                cleaned_text = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', cleaned_text, flags=re.DOTALL).strip()
                
                # 寻找括号里面的内容 [ ... ]
                match = re.search(r'\[\s*.*?\s*\]', cleaned_text, flags=re.DOTALL)
                if match:
                    json_str = match.group(0)
                    try:
                        parsed = json.loads(json_str)
                        if isinstance(parsed, list):
                            answers = [str(item) for item in parsed]
                    except Exception:
                        pass
                
                if not answers:
                    try:
                        parsed = json.loads(cleaned_text)
                        if isinstance(parsed, list):
                            answers = [str(item) for item in parsed]
                    except Exception:
                        pass
                
                # 兜底：如果没有成功解析为 list，按换行/逗号拆分，或如果是单空格直接放进去
                if not answers:
                    num_blanks = len(blank_elements)
                    if num_blanks == 1:
                        answers = [cleaned_text]
                    else:
                        # 尝试通过逗号或换行拆分
                        lines = [l.strip().strip('"\'') for l in cleaned_text.split('\n') if l.strip()]
                        answers = [l for l in lines if l]
                
                # 补全或截断
                num_blanks = len(blank_elements)
                if len(answers) < num_blanks:
                    logger.warning(f"AI返回的答案数 ({len(answers)}) 小于题目填空格数 ({num_blanks})，补充空字符串")
                    answers = answers + [""] * (num_blanks - len(answers))
                elif len(answers) > num_blanks:
                    logger.warning(f"AI返回的答案数 ({len(answers)}) 大于题目填空格数 ({num_blanks})，进行截断")
                    answers = answers[:num_blanks]
                
                # 填入网页
                for index, answer in enumerate(answers):
                    blank_elem = blank_elements[index]
                    await blank_elem.scroll_into_view_if_needed()
                    await blank_elem.fill(answer)
                    await asyncio.sleep(0.3)
                    logger.info(f"填空处 {index + 1} 已填入: {answer}")
            else:
                indices = re.findall(r'(\d+)', answer_text)
                unique_indices = list(dict.fromkeys([int(idx) for idx in indices if idx.isdigit()]))
                
                # 如果没找到有效数字索引，尝试匹配字母 A, B, C, D...
                if not unique_indices:
                    letters = re.findall(r'\b([A-Za-z])\b', answer_text)
                    if letters:
                        for letter in letters:
                            # 找到字母对应的选项索引
                            for idx, opt in enumerate(options):
                                if opt[0].upper() == letter.upper():
                                    unique_indices.append(idx + 1)
                                    logger.info(f"解析到字母选项: {letter.upper()}，对应索引 {idx + 1}")
    
                if not unique_indices:
                    logger.warning("没有匹配到有效的数字或字母选项索引")
                    print("【暂停答题】AI未返回有效选项，请手动处理后按回车键继续...")
                    await async_input()
                    logger.info("用户已确认，继续答题")
                    return
        
                logger.info(f"解析出的选项索引: {unique_indices}")
                
                # 防止单选题或判断题下触发多次点击逻辑
                is_single = '单选' in subject_type or '判断' in subject_type
                if is_single and len(unique_indices) > 1:
                    logger.info(f"检测到单选/判断题，仅保留第一个解析出的选项索引: {unique_indices[:1]}")
                    unique_indices = unique_indices[:1]
                
                if not skip_completed_questions and '多选' in subject_type:
                    logger.info("重做模式下的多选题，先取消已选择的选项")
                    
                    # 使用标准的 CSS :has 伪类选取已选中的 nodeLab 元素，避免复杂的 XPath 向上查找
                    selected_node_labs = await current_subject.query_selector_all('div.nodeLab:has(span.flagChecked:not([style*="display: none"]))')
                    for node in selected_node_labs:
                        await node.click()
                        logger.info("已取消一个已选中的选项")
                
                for index in unique_indices:
                    array_index = index - 1
                    if 0 <= array_index < len(option_elements):
                        target_option = option_elements[array_index]
                        
                        await target_option.click()
                        logger.info(f"已选择选项 {options[array_index][0]} (数字索引: {index})")
                    else:
                        logger.warning(f"选项索引超出范围: {index}")
                        array_index = index - 1
                        if 0 <= array_index < len(options):
                            target_option = option_elements[array_index]
                            await target_option.click()
                            logger.info(f"已选择选项 {options[array_index][0]} (通过边界扩展，数字索引: {index})")

            await asyncio.sleep(0.5)
            
            subject_containers = await page.query_selector_all('div.examPaper_subject')
            current_subject = None
            current_question_num = 0
            
            for i, container in enumerate(subject_containers):
                is_visible = await container.is_visible()
                if is_visible:
                    current_subject = container
                    try:
                        num_element = await container.query_selector('div.subject_num.fl span')
                        if num_element:
                            current_num_text = await num_element.inner_text()
                            import re
                            num_match = re.search(r'(\d+)', current_num_text)
                            if num_match:
                                current_question_num = int(num_match.group(1))
                            else:
                                logger.warning(f"无法从 '{current_num_text}' 中提取数字")
                                current_question_num = 0
                        else:
                            logger.warning("未找到题目序号元素")
                            current_question_num = 0
                    except Exception as e:
                        logger.warning(f"获取题目序号时出错: {e}")
                        current_question_num = 0
                    break
            
            if current_question_num >= total_questions:
                next_button = await page.query_selector('button.el-button--primary.is-plain:has-text("保存")')
                if next_button:
                    await next_button.click()
                    logger.info("已点击保存按钮（最后一题）")
                    
                    await asyncio.sleep(1)
                    
                    print("【提示】已保存，请手动检查并决定是否提交考试")
                    logger.info("最后一题已保存，等待用户手动操作")
                else:
                    next_button = await page.query_selector('button:has-text("保存")')
                    if next_button:
                        await next_button.click()
                        logger.info("已点击保存按钮（最后一题）")
                        
                        await asyncio.sleep(1)
                        
                        print("【提示】最后一题已保存，请手动检查并决定是否提交考试")
                        logger.info("最后一题已保存，等待用户手动操作")
                    else:
                        logger.warning("未找到保存按钮")
            else:
                next_button = await page.query_selector('button.el-button--primary.is-plain:has-text("下一题")')
                if next_button:
                    await next_button.click()
                    logger.info("已点击下一题按钮")
                else:
                    next_button = await page.query_selector('button:has-text("下一题")')
                    if next_button:
                        await next_button.click()
                        logger.info("已点击下一题按钮")
                    else:
                        logger.warning("未找到下一题按钮")
                        
                        if current_question_num >= total_questions:
                            logger.info(f"已完成所有题目 ({current_question_num}/{total_questions})，请手动检查并决定是否提交")
                        else:
                            print("【暂停答题】未找到下一题按钮，请手动处理后按回车键继续...")
                            await async_input()
                            logger.info("用户已确认，继续答题")
                
                # 等待页面题号更新为下一题，防止后续迭代产生题号不一致警报
                if question_num < total_questions:
                    logger.info(f"等待页面更新到下一题 (第 {question_num + 1} 题)...")
                    if await wait_for_question_number(page, question_num + 1, timeout=5):
                        logger.info("页面已成功更新到下一题")
                    else:
                        logger.warning("页面在超时内未检测到题号变化，继续尝试")
    except httpx.TimeoutException:
        logger.error("请求大模型API超时，请检查网络或更换更快的模型")
        print("【暂停答题】API响应超时，请手动处理后按回车键继续...")
        await async_input()
        logger.info("用户已确认，继续答题")
        return
    except Exception as click_error:
        logger.error(f"处理题目或点击按钮失败: {click_error}")
        
        subject_containers = await page.query_selector_all('div.examPaper_subject')
        current_subject = None
        current_question_num = 0
        
        for i, container in enumerate(subject_containers):
            is_visible = await container.is_visible()
            if is_visible:
                current_subject = container
                try:
                    num_element = await container.query_selector('div.subject_num.fl span')
                    if num_element:
                        current_num_text = await num_element.inner_text()
                        import re
                        num_match = re.search(r'(\d+)', current_num_text)
                        if num_match:
                            current_question_num = int(num_match.group(1))
                        else:
                            current_question_num = 0
                    else:
                        current_question_num = 0
                except Exception:
                    current_question_num = 0
                break
        
        if current_question_num >= total_questions:
            logger.info(f"已完成所有题目 ({current_question_num}/{total_questions})，请手动检查并决定是否提交")
        else:
            print("【暂停答题】无法点击按钮，请手动处理后按回车键继续...")
            await async_input()
            logger.info("用户已确认，继续答题")

async def get_subject_description_by_vl_ocr(page):
    """对当前题干区域截图并调用 OCR 获取题目文本。"""
    logger.info("开始获取题目描述")
    screenshot_path = None

    try:
        subject_containers = await page.query_selector_all('div.examPaper_subject')
        if not subject_containers:
            logger.error("未找到任何题目容器")
            return "无题目描述"
        
        current_subject = None
        for container in subject_containers:
            is_visible = await container.is_visible()
            if is_visible:
                current_subject = container
                break
        
        if not current_subject:
            logger.warning("未找到当前显示的题目")
            return "无题目描述"
        
        subject_describe_elements = await current_subject.query_selector_all('div.subject_describe.dynamic-fonts')
        if not subject_describe_elements:
            subject_describe_elements = await current_subject.query_selector_all('div.subject_describe')
            
        if not subject_describe_elements:
            logger.warning("未找到题目描述元素")
            return "无题目描述"
        
        subject_element = subject_describe_elements[0]
        
        if subject_element:
            try:
                await page.wait_for_selector('div.subject_describe', state='attached')
                logger.info("题目描述元素已附加到DOM中")
            except Exception as attach_error:
                logger.warning(f"题目描述元素未附加到DOM中: {attach_error}")
                return "无题目描述"
            
            screenshot_dir = ".ocr_screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            screenshot_path = os.path.join(screenshot_dir, f"ocr_screenshot_{timestamp}.png")
            
            try:
                await subject_element.screenshot(path=screenshot_path)
                logger.info(f"成功截取题目描述区域: {screenshot_path}")
            except Exception as screenshot_error:
                logger.error(f"题目描述截图失败: {screenshot_error}")
                return "无题目描述"
            
            if not os.path.exists(screenshot_path):
                logger.error("截图文件未生成")
                return "无题目描述"
            
            with open(screenshot_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')
            
            api_key = os.getenv('QWEN_API_KEY')
            if not api_key:
                logger.error("未找到QWEN_API_KEY环境变量")
                return "无题目描述"
            
            ocr_model_name = os.getenv('OCR_MODEL', 'qwen3.6-plus')
            logger.info(f"使用OCR模型: {ocr_model_name}")
            
            base_endpoint = os.getenv('QWEN_ENDPOINT') or os.getenv('BASE_URL') or os.getenv('DASHSCOPE_BASE_URL') or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            if "/chat/completions" in base_endpoint:
                url = base_endpoint
            else:
                url = f"{base_endpoint.rstrip('/')}/chat/completions"
            
            payload = {
                "model": ocr_model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "请识别这张截图中的当前题目题干部分，只需要返回识别到的文字内容，不要包含选项或其他内容，不要其他解释。"
                            }
                        ]
                    }
                ]
            }
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                
                result = response.json()
                ocr_result = result['choices'][0]['message']['content']
                
                if isinstance(ocr_result, list) and len(ocr_result) > 0:
                    if 'text' in ocr_result[0]:
                        subject_describe = ocr_result[0]['text'].strip()
                    else:
                        subject_describe = str(ocr_result).strip()
                else:
                    subject_describe = str(ocr_result).strip()
                
                import re
                subject_describe = re.sub(r'^\d+\.?\s*【[^】]*】\s*\([^)]*\)\s*', '', subject_describe)
                subject_describe = subject_describe.strip()
                
                if subject_describe and not subject_describe.startswith("A.") and not subject_describe.startswith("B.") and not subject_describe.startswith("C.") and not subject_describe.startswith("D."):
                    logger.info(f"通过OCR获取到题目描述: {subject_describe}")
                    return subject_describe
                else:
                    logger.warning(f"OCR获取到的内容看起来像选项或无效内容: {subject_describe}")
                    return "无题目描述"
        else:
            logger.warning("未找到题目描述元素")
            return "无题目描述"
                
    except Exception as e:
        logger.error(f"OCR获取题目描述时出错: {e}")
        import traceback
        traceback.print_exc()
        return "无题目描述"
    finally:
        if screenshot_path and os.path.exists(screenshot_path):
            os.remove(screenshot_path)

async def get_total_questions(page):
    """优先从考试信息读取题目总数，失败时按题目容器数量兜底。"""
    try:
        total_elements = await page.query_selector_all('div.examPaper_partTit span')
        if total_elements:
            total_text = await total_elements[0].inner_text()
            total_questions = int(total_text)
            return total_questions
        else:
            subject_elements = await page.query_selector_all('div.examPaper_subject')
            return len(subject_elements) if subject_elements else 0
    except Exception as e:
        logger.error(f"获取题目总数时出错: {e}")
        try:
            subject_elements = await page.query_selector_all('div.examPaper_subject')
            return len(subject_elements) if subject_elements else 10
        except Exception as fallback_error:
            logger.warning(f"兜底统计题目数失败，使用默认值 10: {fallback_error}")
            return 10

async def process_exam(page, exam_url, username, userPassword, total_questions=None, reference_manager=None):
    """处理单个考试：如果提供了 URL 则打开，否则直接在当前页面检测登录并逐题作答。"""
    if exam_url:
        await page.goto(exam_url)
        logger.info("已打开考试页面")

        # 如果跳转后需要重新登录
        try:
            logger.info("等待页面加载（检测登录页或考试页）...")
            
            task_login = asyncio.create_task(page.wait_for_selector('input[name="username"]', timeout=15000))
            task_exam = asyncio.create_task(page.wait_for_selector('div.examPaper_subject, div.subject_stem', timeout=15000))
            
            done, pending = await asyncio.wait(
                [task_login, task_exam],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 取消所有未完成的任务，避免后台报错
            for task in pending:
                task.cancel()
                
            # 判断是哪个任务先完成且成功
            login_detected = task_login in done and not task_login.cancelled() and task_login.exception() is None
            exam_detected = task_exam in done and not task_exam.cancelled() and task_exam.exception() is None
            
            if login_detected:
                logger.info("检测到登录页面，开始登录流程...")
                print("正在输入手机号、密码")
                await page.fill('input[name="username"]', username)
                await page.fill('input[name="password"]', userPassword)
                await asyncio.sleep(0.8)
                print("正在点击登录按钮...")
                await page.click('.wall-sub-btn')
                logger.info("已点击登录按钮")
                logger.info("正在等待回到考试页面...")
                print("【请接管】请手动完成验证码输入（回到考试页面会自动进行下一步）")
                await page.wait_for_selector('div.examPaper_subject', timeout=300000)
                logger.info("已进入考试页面")
            else:
                logger.info("检测到已处于登录状态，直接进入考试页面")
                
        except Exception as e:
            logger.info(f"等待页面加载出错或超时，尝试兜底检测: {e}")
            try:
                await page.wait_for_selector('div.examPaper_subject', timeout=15000)
                logger.info("检测到考试题目容器")
            except Exception:
                logger.warning("未检测到考试题目容器，可能页面未正确加载")
    else:
        logger.info("没有提供考试URL，假设用户已手动导航到考试页面")
        try:
            await page.wait_for_selector('div.examPaper_subject.mt20', timeout=15000)
            logger.info("检测到考试题目容器")
        except Exception:
            logger.warning("未检测到考试题目容器，请确保已进入考试作答页面")

    await page.wait_for_load_state('domcontentloaded')

    # 检测并处理开始考试前的验证码弹窗
    await check_and_handle_captcha(page)

    try:
        exam_info_element = await page.query_selector('div.examInfo.infoList.hasNotes')
        if exam_info_element:
            question_count_element = await exam_info_element.query_selector('li:has(> label:has-text("题目数")) span')
            if question_count_element:
                total_questions_str = await question_count_element.inner_text()
                total_questions = int(total_questions_str.strip())
                logger.info(f"检测到考试题目总数: {total_questions}")
                print(f"考试题目总数: {total_questions}")
            else:
                logger.warning("未能获取题目数，使用默认方法获取题目总数")
                total_questions = await get_total_questions(page)

            exam_name_element = await exam_info_element.query_selector('li:has(> label:has-text("名称")) span')
            if exam_name_element:
                exam_name = await exam_name_element.inner_text()
                logger.info(f"考试名称: {exam_name}")
                print(f"考试名称: {exam_name}")

            deadline_element = await exam_info_element.query_selector('li:has(> label:has-text("截止时间")) span')
            if deadline_element:
                deadline = await deadline_element.inner_text()
                logger.info(f"截止时间: {deadline}")
                print(f"截止时间: {deadline}")
        else:
            logger.warning("未能获取考试信息，使用默认方法获取题目总数")
            total_questions = await get_total_questions(page)
    except Exception as e:
        logger.warning(f"检测考试信息时出错: {e}，使用默认方法获取题目总数")
        total_questions = await get_total_questions(page)

    try:
        await page.wait_for_selector('div.subject_stem', state='attached', timeout=10000)
        logger.info("检测到题目")
    except Exception:
        logger.warning("未检测到题目容器 div.subject_stem，继续尝试...")

    logger.info(f"总共 {total_questions} 题")

    for i in range(1, total_questions + 1):
        logger.info(f"开始处理第 {i} 题")

        await ai_answer_question(page, i, total_questions, reference_manager=reference_manager)

        await asyncio.sleep(1)

    logger.info("所有题目处理完成")

    print("【执行完成】所有题目已处理并保存")
    print("请手动检查答案并决定是否提交考试")


async def zhihuishu_exam_automation():
    """考试主流程：登录、逐题调用 AI 作答，支持连续处理多个考试。"""
    reference_manager = ReferenceManager()
    
    # 优先从 .env 文件中加载配置以避免 Windows 下 USERNAME 环境变量冲突的问题
    env_dict = dotenv_values(".env") if os.path.exists(".env") else {}
    
    # 尝试获取用户名（优先使用 ZHIHUISHU_USERNAME / ZH_USERNAME）
    env_username = (
        env_dict.get("ZHIHUISHU_USERNAME") or 
        env_dict.get("ZH_USERNAME") or 
        env_dict.get("USERNAME") or 
        os.getenv("ZHIHUISHU_USERNAME") or 
        os.getenv("ZH_USERNAME")
    )
    
    # 尝试获取密码（优先使用 ZHIHUISHU_PASSWORD / ZH_PASSWORD）
    env_password = (
        env_dict.get("ZHIHUISHU_PASSWORD") or 
        env_dict.get("ZH_PASSWORD") or 
        env_dict.get("PASSWORD") or 
        os.getenv("ZHIHUISHU_PASSWORD") or 
        os.getenv("ZH_PASSWORD")
    )
    
    # 兜底：如果用户名依然未找到，但系统环境变量中有 USERNAME
    # 仅在 USERNAME 不等于系统当前登录用户名时使用，避免 Windows 下默认读取到系统用户名
    if not env_username:
        import getpass
        try:
            system_user = getpass.getuser()
        except Exception:
            system_user = None
            
        temp_username = os.getenv("USERNAME")
        if temp_username and temp_username != system_user:
            env_username = temp_username
            
    if not env_password:
        env_password = os.getenv("PASSWORD")

    if env_username and env_password:
        username = env_username
        userPassword = env_password
        print(f"使用环境变量配置: 用户名={username}")
    else:
        username = await async_input("请输入用户名(手机号): ")
        userPassword = await async_input("请输入密码: ")

    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        print("错误: 未配置QWEN_API_KEY，无法使用大模型答题功能")
        print("请在.env文件中配置QWEN_API_KEY")
        return

    answer_model = os.getenv("ANSWER_MODEL", "qwen3.6-plus")
    print(f"已检测到API密钥，答题模型: {answer_model}，大模型答题功能已启用")

    use_ai_answer = True

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel='chrome',
                args=['--mute-audio']
            )
        except Exception as launch_err:
            logger.warning(f"启动 Chrome 浏览器通道失败 (可能是未安装 Chrome): {launch_err}。尝试使用默认 Chromium 启动...")
            browser = await p.chromium.launch(
                headless=False,
                args=['--mute-audio']
            )

        context = await browser.new_context()

        page = await context.new_page()

        # 1. 先打开智慧树官网，自动登录
        print("正在打开智慧树官网...")
        await page.goto('https://www.zhihuishu.com')
        logger.info("已打开智慧树官网")

        print("正在打开登陆页面...")
        await page.click('text="登录"')
        logger.info("已点击登录按钮")

        logger.info("正在等待登录页面出现...")
        await page.wait_for_selector('input[name="username"]', timeout=50000)
        logger.info("登录页面已出现")

        print("正在输入手机号、密码")
        logger.info("正在输入手机号...")
        await page.fill('input[name="username"]', username)
        logger.info("手机号已输入")

        logger.info("正在输入密码...")
        await page.fill('input[name="password"]', userPassword)
        logger.info("密码已输入")

        await asyncio.sleep(0.8)

        print("正在点击登录按钮...")
        await page.click('.wall-sub-btn')
        logger.info("已点击登录按钮")
        logger.info("正在等待页面跳转到学习页面...")
        print("【请接管】请手动完成验证码输入（验证码通过后程序会自动继续）")

        # 等待登录成功，跳转到学习页面
        try:
            await page.wait_for_url('https://onlineweb.zhihuishu.com/onlinestuh5', timeout=60000)
            print("已跳转到课程列表页面，登录成功")
        except Exception:
            # 也可能跳转到其他页面
            await asyncio.sleep(5)
            logger.info("等待登录完成，继续...")

        # 2. 循环处理考试
        first_run = True
        while True:
            print("\n" + "=" * 50)

            exam_url = os.getenv("EXAM_URL") if first_run else None
            
            if exam_url and exam_url.strip():
                print(f"检测到已配置考试URL: {exam_url}")
                print("正在自动打开考试页面...")
                await process_exam(page, exam_url, username, userPassword, reference_manager=reference_manager)
            else:
                while True:
                    print("【输入提示】")
                    choice = (await async_input("请输入考试 URL 并按回车(Enter)开始答题: ")).strip()
                    if choice:
                        if choice.startswith("http://") or choice.startswith("https://"):
                            print(f"正在打开考试页面: {choice}")
                            await process_exam(page, choice, username, userPassword, reference_manager=reference_manager)
                            break
                        else:
                            print("错误: 请输入以 http:// 或 https:// 开头的有效 URL 链接！\n")
                    else:
                        print("错误: 考试 URL 不能为空，请输入有效的考试 URL 链接！\n")

            first_run = False
            print("\n" + "=" * 50)
            print("【询问】是否还有下一个考试需要处理？")
            another = (await async_input("输入 y 继续，其他键退出: ")).strip().lower()
            if another not in ['y', 'yes', '是']:
                print("程序结束，浏览器保持打开状态...")
                break

            print("准备处理下一个考试...")

if __name__ == "__main__":
    asyncio.run(zhihuishu_exam_automation())
