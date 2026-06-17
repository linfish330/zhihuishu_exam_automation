#!/usr/bin/env python3
"""
智慧树课程视频批量下载工具

基于 Playwright 浏览器自动化，自动登录智慧树平台、进入指定课程、
提取全部视频 URL 并批量下载到本地。

用法:
    python zhihuishu_video_downloader.py
"""

import asyncio
import os
import re
import sys
import time
import logging
import base64
import subprocess
from pathlib import Path

from dotenv import load_dotenv, dotenv_values
load_dotenv()

import httpx
from playwright.async_api import async_playwright

# ─── 日志配置 ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# ─── 工具函数 ─────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    """移除文件名中不允许的字符。"""
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    name = name.strip('. ')
    return name or "untitled"


def format_size(size_bytes: int) -> str:
    """将字节数格式化为可读字符串。"""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ─── 弹窗处理 ─────────────────────────────────────────────

async def handle_captcha(page):
    """检测验证码弹窗，出现时提示人工处理并等待消失。"""
    try:
        modal = await page.query_selector("div.yidun_modal")
        if modal and await modal.is_visible():
            logger.info("检测到验证码弹窗，请手动完成验证...")
            print("\n【请接管】请手动完成弹窗验证码输入\n")
            await page.wait_for_selector("div.yidun_modal", state="hidden", timeout=600_000)
            logger.info("验证码处理完成")
    except Exception as e:
        logger.warning(f"检测验证码时出错: {e}")


async def handle_integrity_commitment(page):
    """处理「在线学习诚信承诺书」弹窗。"""
    try:
        selector = 'div[role="dialog"][aria-label="在线学习诚信承诺书"]'
        dialog = page.locator(selector).first
        if await dialog.count() == 0 or not await dialog.is_visible():
            return

        logger.info("检测到诚信承诺书弹窗，自动确认...")
        checkbox = dialog.locator('input[type="checkbox"]').first
        if await checkbox.count() > 0 and not await checkbox.is_checked():
            await checkbox.check(force=True)

        confirm_btn = dialog.locator("button.agree-btn, button:has-text('确认')").first
        if await confirm_btn.count() > 0:
            await confirm_btn.wait_for(state="visible", timeout=5000)
            for _ in range(10):
                if not await confirm_btn.is_disabled():
                    break
                await asyncio.sleep(0.2)
            await confirm_btn.click(timeout=5000)

        try:
            await page.wait_for_selector(selector, state="hidden", timeout=5000)
        except Exception:
            pass
        logger.info("诚信承诺书已确认关闭")
    except Exception as e:
        logger.warning(f"处理诚信承诺书时出错: {e}")


async def dismiss_popups(page):
    """依次关闭课程页面中可能出现的各种弹窗。"""
    popup_handlers = [
        # 「学习时间已经结束」温馨提示
        ("温馨提示弹窗", lambda: _dismiss_warm_tip(page)),
        # 公众号课程提醒
        ("课程提醒弹窗", lambda: _dismiss_course_remind(page)),
        # 学前必读
        ("学前必读弹窗", lambda: _dismiss_close_icon(page, "i.iconfont.iconguanbi")),
        # AI 助手信息
        ("AI助手信息弹窗", lambda: _dismiss_close_icon(page, "img.icon")),
        # AI 助手悬浮球
        ("AI助手悬浮球", lambda: _dismiss_close_icon(page, "img.ai-close-icon")),
        # 浏览器建议
        ("浏览器建议弹窗", lambda: _dismiss_no_remind(page)),
    ]
    for name, handler in popup_handlers:
        try:
            await handler()
        except Exception as e:
            logger.debug(f"{name} 处理异常(可忽略): {e}")


async def _dismiss_warm_tip(page):
    dialog = page.locator('div.el-dialog[aria-label="温馨提示"]:has-text("学习时间已经结束")').first
    if await dialog.count() > 0 and await dialog.is_visible():
        btn = dialog.locator('button:has-text("我知道了")').first
        if await btn.count() > 0:
            await btn.click(timeout=3000)
        else:
            close = dialog.locator('button[aria-label="Close"]').first
            if await close.count() > 0:
                await close.click(timeout=3000)
        logger.info("已关闭「学习时间已经结束」弹窗")


async def _dismiss_course_remind(page):
    dialog = page.locator('div[role="dialog"][aria-label="课程提醒"]').first
    if await dialog.count() == 0 or not await dialog.is_visible():
        return
    for btn_sel in ("div.rlready-bound-btn", "div.talk-later-btn"):
        btn = dialog.locator(btn_sel).first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click(timeout=3000)
            break
    logger.info("已关闭课程提醒弹窗")


async def _dismiss_close_icon(page, selector):
    await page.wait_for_selector(selector, timeout=3000)
    await page.click(selector)
    logger.info(f"已关闭 {selector} 弹窗")


async def _dismiss_no_remind(page):
    link = page.locator('a:has-text("不再提示")').first
    if await link.count() > 0 and await link.is_visible():
        await link.click(timeout=3000)
        logger.info("已点击「不再提示」")


# ─── 登录与导航 ───────────────────────────────────────────

async def login(page, username: str, password: str):
    """登录智慧树平台。"""
    print("正在打开智慧树官网...")
    await page.goto("https://www.zhihuishu.com")
    logger.info("已打开智慧树官网")

    print("正在打开登录页面...")
    await page.click('text="登录"')
    await page.wait_for_selector('input[name="username"]', timeout=10_000)
    logger.info("登录页面已加载")

    print("正在输入账号密码...")
    await page.fill('input[name="username"]', username)
    await page.fill('input[name="password"]', password)
    await asyncio.sleep(0.8)

    print("正在点击登录...")
    await page.click(".wall-sub-btn")
    logger.info("已提交登录表单")
    print("【请接管】若出现验证码，请手动完成验证（完成后程序自动继续）")

    await page.wait_for_url("https://onlineweb.zhihuishu.com/onlinestuh5", timeout=30_000)
    await asyncio.sleep(3)
    logger.info("登录成功，已进入课程列表页面")
    print("登录成功！")


async def enter_course(page, course_name: str):
    """在课程列表中找到并进入指定课程。"""
    print(f"正在查找课程「{course_name}」...")
    await page.wait_for_selector("div.courseName", timeout=15_000)
    await page.click(f'div.courseName:has-text("{course_name}")')
    logger.info(f"已点击课程「{course_name}」")

    # 等待课程页面加载
    try:
        await page.wait_for_selector(
            "ul.list, [aria-label='在线学习诚信承诺书'], [aria-label='课程提醒']",
            state="attached",
            timeout=30_000,
        )
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        logger.warning("等待课程页面加载超时，继续执行...")

    await handle_integrity_commitment(page)
    await dismiss_popups(page)
    logger.info("已进入课程学习页面，弹窗已清理")
    print("已进入课程页面！")


# ─── 视频数据提取 ─────────────────────────────────────────

async def extract_video_list(page) -> list[dict]:
    """
    从 Vuex Store 中提取完整的视频列表。
    返回格式: [{ videoId, name, chapterName, orderLabel }, ...]
    """
    logger.info("正在从页面 Vuex Store 提取视频列表...")

    js_code = """
    () => {
        // 定位根组件
        var root = document.querySelector('.el-scrollbar');
        if (!root || !root.__vue__) return { error: 'no vue root' };

        var store = root.__vue__.$store;
        if (!store) return { error: 'no store' };

        // 遍历组件树找到包含 videoList 的组件
        var app = root.__vue__.$root.$children[0].$children[0];
        if (!app || !app.videoList) return { error: 'no videoList' };

        var chapters = app.videoList;
        var results = [];

        chapters.forEach(function(ch, chIdx) {
            var chName = ch.name || ('第' + (chIdx + 1) + '章');
            (ch.videoLessons || []).forEach(function(lesson) {
                var baseLabel = chIdx + 1 + '.' + lesson.orderNumber;
                // 如果有子课程(videoSmallLessons)，展开子课程
                if (lesson.ishaveChildrenLesson && lesson.videoSmallLessons) {
                    lesson.videoSmallLessons.forEach(function(sub, subIdx) {
                        results.push({
                            videoId: sub.videoId,
                            name: sub.name,
                            chapterName: chName,
                            orderLabel: baseLabel + '.' + (subIdx + 1)
                        });
                    });
                } else if (lesson.videoId) {
                    results.push({
                        videoId: lesson.videoId,
                        name: lesson.name,
                        chapterName: chName,
                        orderLabel: baseLabel
                    });
                }
            });
        });

        return { count: results.length, videos: results };
    }
    """
    result = await page.evaluate(js_code)

    if "error" in result:
        raise RuntimeError(f"提取视频列表失败: {result['error']}")

    videos = result["videos"]
    logger.info(f"成功提取 {len(videos)} 个视频信息")
    return videos


async def fetch_video_urls(page, videos: list[dict]) -> list[dict]:
    """
    通过 JSONP 调用 initVideo 接口获取每个视频的实际播放 URL。
    返回带有 url 字段的完整视频列表。
    """
    logger.info(f"正在获取 {len(videos)} 个视频的播放地址...")

    # 注入 JSONP 辅助函数
    await page.evaluate("""
    () => {
        window._videoUrls = {};
        window._jsonpCounter = 0;
        window._fetchOneVideo = function(videoId) {
            window._jsonpCounter++;
            var cbName = '_dlVideoCb_' + window._jsonpCounter;
            window[cbName] = function(data) {
                if (data && data.result && data.result.lines) {
                    var line = data.result.lines.find(function(l) { return l.lineDefault; }) || data.result.lines[0];
                    window._videoUrls[videoId] = line ? line.lineUrl : '';
                }
                try { delete window[cbName]; } catch(e) { window[cbName] = undefined; }
            };
            var s = document.createElement('script');
            s.src = 'https://newbase.zhihuishu.com/video/initVideo?jsonpCallBack='
                  + cbName + '&videoID=' + videoId + '&_=' + Date.now() + window._jsonpCounter;
            document.head.appendChild(s);
        };
    }
    """)

    # 分批触发 JSONP 请求（每批 10 个，间隔 300ms 避免请求过于密集）
    batch_size = 10
    for i in range(0, len(videos), batch_size):
        batch = videos[i : i + batch_size]
        ids = [v["videoId"] for v in batch]
        await page.evaluate("""
        (ids) => {
            ids.forEach(function(vid, idx) {
                setTimeout(function() { window._fetchOneVideo(vid); }, idx * 300);
            });
        }
        """, ids)
        # 等待本批请求完成
        await asyncio.sleep(len(batch) * 0.3 + 1.5)

    # 收集结果
    url_map = await page.evaluate("() => window._videoUrls")
    found, missing = 0, 0
    for v in videos:
        vid = str(v["videoId"])
        raw_url = url_map.get(vid, "")
        if raw_url:
            v["url_low"] = raw_url  # _512 标清
            v["url_high"] = raw_url.replace("_512.mp4", ".mp4")  # 高清
            found += 1
        else:
            v["url_low"] = ""
            v["url_high"] = ""
            missing += 1
            logger.warning(f"未获取到视频 URL: {v['orderLabel']} {v['name']} (videoId={vid})")

    logger.info(f"URL 获取完成: 成功 {found}, 失败 {missing}")
    return videos


# ─── 视频下载 ─────────────────────────────────────────────

async def download_one_video(
    client: httpx.AsyncClient,
    video: dict,
    save_dir: Path,
    quality: str,
    semaphore: asyncio.Semaphore,
) -> bool:
    """下载单个视频文件，支持断点续传与进度显示。"""
    url_key = "url_high" if quality == "high" else "url_low"
    url = video.get(url_key) or video.get("url_high") or video.get("url_low")
    if not url:
        logger.error(f"跳过无 URL 的视频: {video['orderLabel']} {video['name']}")
        return False

    filename = sanitize_filename(f"{video['orderLabel']} {video['name']}") + ".mp4"
    filepath = save_dir / filename

    # 跳过已下载的文件
    if filepath.exists() and filepath.stat().st_size > 0:
        logger.info(f"[跳过] {filename} (已存在)")
        return True

    tmp_path = filepath.with_suffix(".mp4.tmp")

    async with semaphore:
        logger.info(f"[开始] {filename}")
        try:
            headers = {"Referer": "https://studyvideoh5.zhihuishu.com/"}
            async with client.stream("GET", url, headers=headers, timeout=600) as resp:
                if resp.status_code not in (200, 206):
                    logger.error(f"[失败] {filename}: HTTP {resp.status_code}")
                    return False

                total = int(resp.headers.get("content-length", 0))
                downloaded = 0

                with open(tmp_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = downloaded / total * 100
                            if int(pct) % 20 == 0 and downloaded == len(chunk):
                                pass  # 避免刷屏

            # 下载完成，重命名
            tmp_path.rename(filepath)
            size_str = format_size(filepath.stat().st_size)
            logger.info(f"[完成] {filename} ({size_str})")
            return True

        except Exception as e:
            logger.error(f"[失败] {filename}: {e}")
            if tmp_path.exists():
                tmp_path.unlink()
            return False


async def download_all_videos(
    videos: list[dict],
    save_dir: Path,
    quality: str,
    concurrent: int,
):
    """批量下载所有视频。"""
    save_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(concurrent)

    # 使用 HTTP/1.1 transport（智慧树 CDN 对 HTTP/2 有兼容问题）
    transport = httpx.AsyncHTTPTransport(http1=True)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        tasks = [
            download_one_video(client, v, save_dir, quality, semaphore)
            for v in videos
        ]
        results = await asyncio.gather(*tasks)

    success = sum(1 for r in results if r)
    fail = sum(1 for r in results if not r)
    logger.info(f"下载完成: 成功 {success}/{len(videos)}, 失败 {fail}")

    if fail > 0:
        logger.warning("以下视频下载失败，可重新运行脚本（已下载的会自动跳过）:")
        for v, ok in zip(videos, results):
            if not ok:
                logger.warning(f"  - {v['orderLabel']} {v['name']}")


# ─── 语音识别与转写 ─────────────────────────────────────────

def convert_video_to_audio(video_path: Path, audio_path: Path):
    logger.info(f"正在提取音频: {video_path.name} -> {audio_path.name}")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "libmp3lame",
        "-ac", "1",
        "-ar", "16000",
        "-ab", "64k",
        str(audio_path)
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg 转换失败: {result.returncode}")
        logger.error(f"Stderr: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

def split_audio(audio_path: Path, chunk_dir: Path, chunk_duration: int = 300):
    logger.info(f"正在切分音频 {audio_path.name} 到 {chunk_dir.name}")
    chunk_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-f", "segment",
        "-segment_time", str(chunk_duration),
        "-c", "copy",
        str(chunk_dir / "chunk_%03d.mp3")
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg 切片失败: {result.returncode}")
        logger.error(f"Stderr: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

async def transcribe_chunk(client: httpx.AsyncClient, chunk_path: Path) -> str:
    with open(chunk_path, "rb") as f:
        audio_data = f.read()
    
    size_mb = len(audio_data) / (1024 * 1024)
    logger.info(f"正在转写分片: {chunk_path.name} (大小: {size_mb:.2f} MB)")
    
    audio_base64 = base64.b64encode(audio_data).decode("utf-8")
    
    api_key = os.getenv("MIMO_API_KEY", "")
    base_url = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
    model_name = os.getenv("MIMO_MODEL", "mimo-v2.5-asr")
    api_url = f"{base_url.rstrip('/')}/chat/completions"
    
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }
    
    # Try mimo-v2.5-asr first
    asr_payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:audio/mp3;base64,{audio_base64}"
                        }
                    }
                ]
            }
        ],
        "asr_options": {
            "language": "zh"
        }
    }
    
    try:
        logger.info(f"尝试调用 ASR 模型 {model_name}...")
        resp = await client.post(api_url, headers=headers, json=asr_payload, timeout=120)
        if resp.status_code == 200:
            result_json = resp.json()
            text = result_json["choices"][0]["message"]["content"]
            logger.info("ASR 模型转写成功")
            return text
        else:
            logger.warning(f"ASR 模型返回状态码: {resp.status_code}. 响应: {resp.text}")
    except Exception as e:
        logger.error(f"ASR 模型请求出错: {e}")
        
    # Fallback to mimo-v2.5
    logger.info("触发备用模型 mimo-v2.5 进行多模态语音转写...")
    multimodal_payload = {
        "model": "mimo-v2.5",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:audio/mp3;base64,{audio_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": "请将这段音频的内容转写为文本，直接输出转写结果，不要包含任何解释或前言。"
                    }
                ]
            }
        ]
    }
    
    max_retries = 5
    backoff = 2
    for attempt in range(max_retries):
        try:
            resp = await client.post(api_url, headers=headers, json=multimodal_payload, timeout=120)
            if resp.status_code == 200:
                result_json = resp.json()
                text = result_json["choices"][0]["message"]["content"]
                logger.info("多模态模型转写成功")
                return text
            elif resp.status_code == 429:
                logger.warning(f"限流 (429). 将在 {backoff} 秒后重试...")
            else:
                logger.warning(f"接口返回状态码: {resp.status_code}. 响应: {resp.text}")
                logger.warning(f"将在 {backoff} 秒后重试...")
        except Exception as e:
            logger.error(f"网络请求出错: {e}")
            logger.warning(f"将在 {backoff} 秒后重试...")
            
        await asyncio.sleep(backoff)
        backoff *= 2
        
    raise RuntimeError(f"经过 {max_retries} 次尝试后仍无法转写分片 {chunk_path.name}")

def clean_directory(dir_path: Path):
    if dir_path.exists():
        for f in dir_path.glob("*"):
            if f.is_file():
                f.unlink()
        dir_path.rmdir()

async def process_video(client: httpx.AsyncClient, video_path: Path, markdown_dir: Path):
    base_name = video_path.stem
    markdown_path = markdown_dir / f"{base_name}.md"
    
    if markdown_path.exists() and markdown_path.stat().st_size > 0:
        logger.info(f"[转写跳过] {video_path.name} (Markdown 已存在)")
        if video_path.exists():
            try:
                video_path.unlink()
                logger.info(f"🗑️ Markdown 已存在，删除对应的视频文件: {video_path.name}")
            except Exception as e:
                logger.error(f"删除已转写视频 {video_path.name} 失败: {e}")
        return
        
    logger.info(f"=== 开始转写: {video_path.name} ===")
    
    temp_audio_path = video_path.parent / f"{base_name}_temp.mp3"
    chunk_dir = video_path.parent / f"{base_name}_temp_chunks"
    
    success = False
    try:
        convert_video_to_audio(video_path, temp_audio_path)
        split_audio(temp_audio_path, chunk_dir)
        
        chunk_files = sorted(chunk_dir.glob("chunk_*.mp3"))
        if not chunk_files:
            logger.error(f"未生成任何切片文件: {video_path.name}")
            return
            
        transcriptions = []
        for idx, chunk in enumerate(chunk_files):
            logger.info(f"正在转写分片 {idx + 1}/{len(chunk_files)}: {video_path.name}")
            text = await transcribe_chunk(client, chunk)
            if text:
                transcriptions.append(text.strip())
                
        full_text = "\n\n".join(transcriptions)
        markdown_content = f"# {base_name}\n\n{full_text}\n"
        
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"🎉 成功保存转写文档: {markdown_path.name}")
        success = True
        
    except Exception as e:
        logger.error(f"转写视频 {video_path.name} 时出错: {e}")
        if markdown_path.exists():
            markdown_path.unlink()
    finally:
        if temp_audio_path.exists():
            temp_audio_path.unlink()
        clean_directory(chunk_dir)
        
        if success and video_path.exists():
            try:
                video_path.unlink()
                logger.info(f"🗑️ 转写成功，已删除原视频文件: {video_path.name}")
            except Exception as e:
                logger.error(f"删除视频文件 {video_path.name} 失败: {e}")

async def transcribe_all_videos(save_dir: Path, course_name: str):
    api_key = os.getenv("MIMO_API_KEY", "")
    if not api_key:
        logger.warning("未配置 MIMO_API_KEY，将跳过视频转写步骤。")
        return
        
    markdown_dir = Path(__file__).parent / "reference_materials"
    if course_name:
        markdown_dir = markdown_dir / sanitize_filename(course_name)
    markdown_dir.mkdir(parents=True, exist_ok=True)
    
    video_files = sorted(save_dir.glob("*.mp4"))
    if not video_files:
        logger.info("未找到需要转写的视频。")
        return
        
    logger.info(f"\n开始自动转写，在 {save_dir} 中找到 {len(video_files)} 个视频。")
    logger.info(f"Markdown 结果将保存至: {markdown_dir}")
    
    transport = httpx.AsyncHTTPTransport(http1=True)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        for idx, video in enumerate(video_files):
            logger.info(f"\n[转写进度] 正在处理 {idx + 1}/{len(video_files)}: {video.name}")
            await process_video(client, video, markdown_dir)
            
    logger.info("✨ 所有视频自动转写完成！")


# ─── 主流程 ───────────────────────────────────────────────

async def main():
    # 优先从 .env 直接读取配置，避免与系统环境变量（如 Windows 上的 USERNAME）冲突
    config = dotenv_values(".env") if os.path.exists(".env") else {}
    username = config.get("USERNAME") or config.get("ZHIHUISHU_USERNAME") or os.getenv("ZHIHUISHU_USERNAME") or os.getenv("ZH_USERNAME")
    
    if not username:
        username_fallback = os.getenv("USERNAME", "")
        if username_fallback:
            # 检查是否为系统内置用户名，若是则忽略，防止在 Windows 上误用系统用户名作为智慧树账号
            system_user = None
            try:
                system_user = os.getlogin()
            except Exception:
                try:
                    import getpass
                    system_user = getpass.getuser()
                except Exception:
                    pass
            if username_fallback != system_user:
                username = username_fallback
            else:
                username = ""

    password = config.get("PASSWORD") or os.getenv("ZHIHUISHU_PASSWORD") or os.getenv("PASSWORD", "")
    course_name = config.get("COURSE_NAME") or os.getenv("COURSE_NAME", "")
    quality = config.get("QUALITY") or os.getenv("QUALITY", "high")
    if isinstance(quality, str):
        quality = quality.strip().lower()
    
    concurrent_val = config.get("CONCURRENT") or os.getenv("CONCURRENT", "3")
    concurrent = int(concurrent_val)

    # 交互式输入（环境变量未配置时）
    if not username:
        username = input("请输入智慧树账号(手机号): ")
    if not password:
        password = input("请输入密码: ")
    if not course_name:
        course_name = input("请输入课程名称: ")

    # 下载目录
    download_dir_env = os.getenv("DOWNLOAD_DIR", "./videos")
    if os.path.isabs(download_dir_env):
        save_dir = Path(download_dir_env)
    else:
        save_dir = Path(__file__).parent / download_dir_env
    save_dir = save_dir / sanitize_filename(course_name)

    print(f"\n{'='*60}")
    print(f"  智慧树视频下载工具")
    print(f"  课程: {course_name}")
    print(f"  画质: {'高清' if quality == 'high' else '标清'}")
    print(f"  并发: {concurrent} 个同时下载")
    print(f"  保存到: {save_dir}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        # 启动浏览器
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--mute-audio"],
            )
        except Exception:
            logger.warning("Chrome 启动失败，尝试使用内置 Chromium...")
            browser = await p.chromium.launch(
                headless=False,
                args=["--mute-audio"],
            )

        page = await browser.new_page()

        try:
            # Step 1: 登录
            await login(page, username, password)

            # Step 2: 进入课程
            await enter_course(page, course_name)

            # Step 3: 提取视频列表
            videos = await extract_video_list(page)
            if not videos:
                logger.error("未找到任何视频，请确认课程名称是否正确")
                return

            print(f"\n找到 {len(videos)} 个视频:")
            for v in videos:
                print(f"  {v['orderLabel']} {v['name']} ({v['chapterName']})")

            # Step 4: 获取视频播放 URL
            videos = await fetch_video_urls(page, videos)

            # Step 5: 关闭浏览器（下载不需要浏览器了）
            print("\n视频 URL 提取完成，正在关闭浏览器...")

        except Exception as e:
            logger.error(f"执行出错: {e}")
            import traceback
            traceback.print_exc()
            return
        finally:
            await browser.close()

    # Step 6: 下载视频
    print(f"\n开始下载 {len(videos)} 个视频到: {save_dir}\n")
    await download_all_videos(videos, save_dir, quality, concurrent)

    # 统计
    if save_dir.exists():
        mp4_files = list(save_dir.glob("*.mp4"))
        total_size = sum(f.stat().st_size for f in mp4_files)
        print(f"\n{'='*60}")
        print(f"  下载完成！")
        print(f"  文件数: {len(mp4_files)}/{len(videos)}")
        print(f"  总大小: {format_size(total_size)}")
        print(f"  保存位置: {save_dir}")
        print(f"{'='*60}")

    # 自动转写
    if save_dir.exists():
        await transcribe_all_videos(save_dir, course_name)


if __name__ == "__main__":
    asyncio.run(main())
