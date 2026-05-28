import asyncio
import json
import re
import time
from datetime import datetime
import httpx
from playwright.async_api import async_playwright
from dotenv import load_dotenv
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

def _clean_thinking_process(text):
    """移除大模型可能返回的思考过程（如 <think>...</think> 或 [thinking]... 等标记）"""
    if not text:
        return ""
    import re
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[thinking\].*?\[/thinking\]', '', text, flags=re.DOTALL)
    return text.strip()

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


async def ai_answer_question(page, question_num, total_questions):
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
    
    is_question_completed = False
    if current_subject:
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
            input()
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
    
    subject_describe = await get_subject_description_by_vl_ocr(page)
    
    options = []
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
        "temperature": 0.3,
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
                input()
                logger.info("用户已确认，继续答题")
                return
    
            logger.info(f"解析出的选项索引: {unique_indices}")
            
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
                            input()
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
        input()
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
            input()
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
            logger.warning("未找到题目描述元素")
            return "无题目描述"
        
        subject_element = subject_describe_elements[0]
        
        if subject_element:
            try:
                await page.wait_for_selector('div.subject_describe.dynamic-fonts', state='attached')
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
                ],
                "temperature": 0.1
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

async def process_exam(page, exam_url, username, userPassword, total_questions=None):
    """处理单个考试：打开URL、检测登录、逐题作答。"""
    await page.goto(exam_url)
    logger.info("已打开考试页面")

    # 如果跳转后需要重新登录
    try:
        logger.info("等待登录页面出现...")
        await page.wait_for_selector('input[name="username"]', timeout=10000)
        logger.info("检测到登录页面")

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
        logger.info("正在等待回到考试页面...")
        print("【请接管】请手动完成验证码输入（回到考试页面会自动进行下一步）")

        await page.wait_for_selector('div.examPaper_subject.mt20', timeout=30000)
        logger.info("已回到考试页面")

    except Exception as login_probe_error:
        logger.info(f"无需登录或已在考试页面: {login_probe_error}")
        try:
            await page.wait_for_selector('div.examPaper_subject.mt20', timeout=30000)
            logger.info("检测到考试题目容器")
        except Exception:
            logger.warning("未检测到考试题目容器，可能页面未正确加载")

    await page.wait_for_load_state('domcontentloaded')

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

        await ai_answer_question(page, i, total_questions)

        await asyncio.sleep(1)

    logger.info("所有题目处理完成")

    print("【执行完成】所有题目已处理并保存")
    print("请手动检查答案并决定是否提交考试")


async def zhihuishu_exam_automation():
    """考试主流程：登录、逐题调用 AI 作答，支持连续处理多个考试。"""
    env_username = os.getenv("USERNAME")
    env_password = os.getenv("PASSWORD")

    if env_username and env_password:
        username = env_username
        userPassword = env_password
        print(f"使用环境变量配置: 用户名={username}")
    else:
        username = input("请输入用户名(手机号): ")
        userPassword = input("请输入密码: ")

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
        while True:
            print("\n" + "=" * 50)

            exam_url = os.getenv("EXAM_URL")
            if exam_url:
                print(f"使用环境变量中的考试页面URL: {exam_url}")
            else:
                exam_url = input("请输入考试页面URL: ")
                print(f"正在打开考试页面: {exam_url}")

            await process_exam(page, exam_url, username, userPassword)

            print("\n" + "=" * 50)
            print("【询问】是否还有下一个考试需要处理？")
            another = input("输入 y 继续，其他键退出: ").strip().lower()
            if another != 'y' and another != 'yes' and another != '是':
                print("程序结束，浏览器保持打开状态...")
                break

            print("准备处理下一个考试...")

if __name__ == "__main__":
    asyncio.run(zhihuishu_exam_automation())
