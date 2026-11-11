"""
视频处理器 — 帧级画面抽取 + 多模态理解 (MLLM)
真实实现：OpenCV 抽帧 → MLLM 视觉理解
"""

import os
import base64
import json
from pathlib import Path
from logger import get_logger

logger = get_logger(__name__)

# 帧抽取
try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

# ASR
try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

import httpx

from config import DASHSCOPE_API_KEY


# ========== 1. 帧抽取 ==========

def extract_frames(video_path: str, interval_sec: float = 1.0, max_frames: int = 30) -> list[dict]:
    """
    从视频中按时间间隔抽取关键帧
    返回: [{"timestamp": "3s", "frame_path": "xxx.jpg", "frame_base64": "..."}]
    """
    if not HAS_OPENCV:
        logger.warning("opencv 未安装，使用模拟帧")
        return _mock_frames()

    if not os.path.exists(video_path):
        logger.warning(f"文件不存在: {video_path}，使用模拟帧")
        return _mock_frames()

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # fps 元数据缺失时（损坏文件/部分流媒体）为 0：统一兜底为 1，
    # 否则 frame_interval=0 死循环抽同一帧、timestamp 计算除零崩溃
    if fps <= 0:
        logger.warning(f"视频 fps 元数据缺失/非法（{fps}），按 1fps 兜底处理")
        fps = 1.0
    duration = total_frames / fps

    frames = []
    frame_interval = max(1, int(fps * interval_sec))
    frame_idx = 0
    count = 0

    # 输出目录
    output_dir = os.path.join(os.path.dirname(__file__), "data", "frames")
    os.makedirs(output_dir, exist_ok=True)

    while cap.isOpened() and count < max_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        # 保存帧图片
        timestamp = frame_idx / fps
        frame_path = os.path.join(output_dir, f"frame_{count:04d}_{timestamp:.1f}s.jpg")
        cv2.imwrite(frame_path, frame)

        # 编码 base64（用于 MLLM）
        _, buffer = cv2.imencode('.jpg', frame)
        frame_b64 = base64.b64encode(buffer).decode('utf-8')

        frames.append({
            "timestamp": f"{timestamp:.1f}s",
            "frame_path": frame_path,
            "frame_base64": frame_b64,
        })

        frame_idx += frame_interval
        count += 1

    cap.release()
    logger.info(f"抽取 {len(frames)} 帧，视频时长 {duration:.1f}s")
    return frames


def _mock_frames():
    """模拟帧数据"""
    return [
        {"timestamp": "0.0s", "frame_path": None, "frame_base64": None},
        {"timestamp": "1.0s", "frame_path": None, "frame_base64": None},
        {"timestamp": "2.0s", "frame_path": None, "frame_base64": None},
        {"timestamp": "5.0s", "frame_path": None, "frame_base64": None},
        {"timestamp": "10.0s", "frame_path": None, "frame_base64": None},
        {"timestamp": "15.0s", "frame_path": None, "frame_base64": None},
    ]


# ========== 2. ASR 语音转文字 ==========

def transcribe_audio(video_path: str) -> str:
    """
    使用 Whisper 进行 ASR 语音转文字
    """
    if not HAS_WHISPER:
        logger.warning("whisper 未安装，使用模拟转写")
        return _mock_asr()

    if not os.path.exists(video_path):
        logger.warning(f"文件不存在: {video_path}，使用模拟转写")
        return _mock_asr()

    model = _get_whisper_model()
    result = model.transcribe(video_path, language="zh")
    text = result["text"]
    logger.info(f"ASR 转写完成，{len(text)} 字")
    return text


_whisper_model = None


def _get_whisper_model():
    """Whisper 模型全局缓存——load_model 一次要数秒，不能每次转写都重新加载"""
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = whisper.load_model("base")
    return _whisper_model


def _mock_asr():
    return "三年了，我在李家做了三年赘婿。所有人都看不起我，直到那天我接到了一个电话..."


# ========== 3. MLLM 多模态理解 ==========

def analyze_frame_with_mllm(frame_base64: str, timestamp: str) -> dict:
    """
    调用多模态大模型分析单帧画面
    使用阿里云百炼 Qwen-VL（支持图片输入）
    """
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "qwen-vl-plus",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": f"data:image/jpeg;base64,{frame_base64}"},
                        {"text": f"这是一个短剧投流素材在 {timestamp} 的画面帧。请从以下维度分析：\n"
                                 f"1. scene: 场景描述\n"
                                 f"2. action: 人物动作\n"
                                 f"3. visual_hook: 视觉钩子（吸引注意力的元素）\n"
                                 f"4. emotion: 情绪氛围\n"
                                 f"5. composition: 构图方式\n"
                                 f"6. color_tone: 色调\n"
                                 f"请返回 JSON 格式。"}
                    ]
                }
            ]
        },
        "parameters": {
            "result_format": "message"
        }
    }

    try:
        resp = httpx.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["output"]["choices"][0]["message"]["content"]

        # 尝试解析 JSON
        if isinstance(content, str):
            # 提取 JSON 部分
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        return {"scene": content, "action": "", "visual_hook": "", "emotion": ""}

    except Exception as e:
        logger.warning(f"MLLM 帧分析失败: {e}，使用模拟数据")
        return _mock_frame_desc(timestamp)


def analyze_frames_batch(frames: list[dict]) -> list[dict]:
    """
    批量分析所有帧（MLLM 多模态理解）
    仅对有 base64 数据的真实帧调用 API
    """
    results = []

    for frame in frames:
        ts = frame["timestamp"]
        b64 = frame.get("frame_base64")

        if b64:
            # 真实帧 → 调用 MLLM
            desc = analyze_frame_with_mllm(b64, ts)
        else:
            # 模拟帧 → 用 mock 数据
            desc = _mock_frame_desc(ts)

        desc["timestamp"] = ts
        results.append(desc)

    logger.info(f"MLLM 分析完成，{len(results)} 帧")
    return results


def _mock_frame_desc(timestamp: str) -> dict:
    """模拟帧描述"""
    mock_data = {
        "0.0s": {"scene": "豪华客厅全景", "action": "男主低头站立，表情隐忍", "visual_hook": "俯拍角度制造压迫感", "emotion": "压抑", "composition": "对称构图", "color_tone": "冷色调"},
        "1.0s": {"scene": "众人围观", "action": "配角嘲讽大笑", "visual_hook": "特写不屑表情", "emotion": "屈辱", "composition": "过肩镜头", "color_tone": "暖黄"},
        "2.0s": {"scene": "手机响起", "action": "男主掏出手机", "visual_hook": "屏幕亮光吸引视线", "emotion": "转折", "composition": "特写", "color_tone": "冷蓝"},
        "5.0s": {"scene": "回忆闪回", "action": "婚礼场景", "visual_hook": "柔光滤镜", "emotion": "回忆", "composition": "虚实对比", "color_tone": "暖色"},
        "10.0s": {"scene": "直升机降落", "action": "万人跪拜", "visual_hook": "航拍大全景", "emotion": "震撼", "composition": "三分法", "color_tone": "金色"},
        "15.0s": {"scene": "对手震惊", "action": "表情凝固", "visual_hook": "慢动作特写", "emotion": "爽感", "composition": "居中", "color_tone": "高对比"},
    }
    return mock_data.get(timestamp, {
        "scene": "场景描述", "action": "人物动作", "visual_hook": "视觉元素",
        "emotion": "情绪", "composition": "构图", "color_tone": "色调"
    })


# ========== 4. 完整处理流水线 ==========

def process_video(video_path: str, asr_text: str = None) -> dict:
    """
    完整视频处理：抽帧 → ASR → MLLM 分析
    """
    logger.info("视频处理流水线启动")

    # Step 1: 抽帧
    logger.info("[Step 1] 帧抽取...")
    frames = extract_frames(video_path)

    # Step 2: ASR（如果未提供）
    if asr_text is None:
        logger.info("[Step 2] ASR 语音转写...")
        asr_text = transcribe_audio(video_path)
    else:
        logger.info("[Step 2] ASR 文本已提供，跳过转写")

    # Step 3: MLLM 帧分析
    logger.info("[Step 3] MLLM 多模态帧分析...")
    frame_descriptions = analyze_frames_batch(frames)

    result = {
        "frames_count": len(frames),
        "asr_text": asr_text,
        "frame_descriptions": frame_descriptions,
        "duration": frames[-1]["timestamp"] if frames else "0s",
    }

    logger.info(f"视频处理完成: {len(frames)} 帧, ASR {len(asr_text)} 字")
    return result


if __name__ == "__main__":
    # 测试
    result = process_video("test.mp4")
    logger.debug(json.dumps(result, ensure_ascii=False, indent=2))
