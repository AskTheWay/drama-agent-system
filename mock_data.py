"""
模拟数据 — 爆款素材知识库 + 模拟视频分析
"""

import json
from models import SessionLocal, HotRef, init_db
from logger import get_logger

logger = get_logger(__name__)

# ========== 爆款素材知识库 ==========

HOT_REFERENCES = [
    {
        "title": "赘婿逆袭：三年隐忍一朝翻盘",
        "category": "男频",
        "sub_category": "逆袭",
        "hook_text": "三年赘婿，所有人都看不起我，直到我接了那个电话...",
        "hook_type": "悬念",
        "emotion_curve": [
            {"time": "0s", "intensity": 0.3, "label": "平静"},
            {"time": "3s", "intensity": 0.7, "label": "紧张"},
            {"time": "8s", "intensity": 0.5, "label": "铺垫"},
            {"time": "15s", "intensity": 0.9, "label": "高潮"},
            {"time": "20s", "intensity": 0.6, "label": "释放"},
        ],
        "beat_points": [
            {"time": "0.5s", "type": "文案出现", "intensity": 0.8, "description": "钩子文案弹出"},
            {"time": "3s", "type": "音乐节拍", "intensity": 0.7, "description": "鼓点重音"},
            {"time": "15s", "type": "画面切换", "intensity": 1.0, "description": "反转画面快切"},
        ],
        "ctr": 0.048,
        "retention_3s": 0.82,
        "completion_rate": 0.35,
        "score": 92.5,
        "tags": ["逆袭", "赘婿", "反转", "爽文"],
        "asr_text": "三年了，我在李家做了三年赘婿。所有人都看不起我，连保姆都敢对我指手画脚。直到那天，我接到了一个电话...",
        "frame_descriptions": [
            {"timestamp": "0s", "scene": "豪华客厅", "action": "男主低头站立", "visual_hook": "俯拍压迫感"},
            {"timestamp": "3s", "scene": "众人嘲笑", "action": "配角嘲讽表情", "visual_hook": "特写不屑眼神"},
            {"timestamp": "15s", "scene": "电话响起", "action": "男主接电话", "visual_hook": "慢动作+光效"},
        ],
    },
    {
        "title": "重生千金：渣男前夫跪地求饶",
        "category": "女频",
        "sub_category": "复仇",
        "hook_text": "重生回到婚礼当天，我微笑着摘下了婚戒...",
        "hook_type": "反转",
        "emotion_curve": [
            {"time": "0s", "intensity": 0.5, "label": "平静"},
            {"time": "2s", "intensity": 0.8, "label": "紧张"},
            {"time": "10s", "intensity": 0.6, "label": "铺垫"},
            {"time": "18s", "intensity": 1.0, "label": "高潮"},
            {"time": "22s", "intensity": 0.4, "label": "释放"},
        ],
        "beat_points": [
            {"time": "0.3s", "type": "文案出现", "intensity": 0.9, "description": "重生宣言"},
            {"time": "5s", "type": "音乐节拍", "intensity": 0.6, "description": "钢琴渐强"},
            {"time": "18s", "type": "特效", "intensity": 1.0, "description": "时间倒流特效"},
        ],
        "ctr": 0.055,
        "retention_3s": 0.88,
        "completion_rate": 0.42,
        "score": 96.0,
        "tags": ["重生", "复仇", "千金", "渣男"],
        "asr_text": "上一世，我为了那个男人放弃了一切，最后却被他和小三联手害死。重生回到婚礼当天，这一次，我微笑着摘下了婚戒...",
        "frame_descriptions": [
            {"timestamp": "0s", "scene": "婚礼现场", "action": "女主微笑", "visual_hook": "暖色调婚纱"},
            {"timestamp": "2s", "scene": "回忆闪回", "action": "上一世惨死", "visual_hook": "冷色调+快切"},
            {"timestamp": "18s", "scene": "摘婚戒", "action": "慢动作摘戒", "visual_hook": "特写手指+光效"},
        ],
    },
    {
        "title": "战神归来：十万将士跪迎",
        "category": "男频",
        "sub_category": "战神",
        "hook_text": "五年后，他从战场归来，身后是十万铁血将士...",
        "hook_type": "利益",
        "emotion_curve": [
            {"time": "0s", "intensity": 0.4, "label": "平静"},
            {"time": "3s", "intensity": 0.8, "label": "紧张"},
            {"time": "10s", "intensity": 0.95, "label": "高潮"},
            {"time": "18s", "intensity": 0.7, "label": "释放"},
        ],
        "beat_points": [
            {"time": "0.5s", "type": "音乐节拍", "intensity": 0.7, "description": "军鼓节奏"},
            {"time": "10s", "type": "画面切换", "intensity": 1.0, "description": "万人跪拜全景"},
        ],
        "ctr": 0.042,
        "retention_3s": 0.78,
        "completion_rate": 0.31,
        "score": 85.0,
        "tags": ["战神", "归来", "热血", "兵王"],
        "asr_text": "五年前，他被陷害入狱，家族覆灭。五年后，他从战场归来，身后是十万铁血将士。曾经欺辱他的人，一个都跑不掉...",
        "frame_descriptions": [
            {"timestamp": "0s", "scene": "荒凉战场", "action": "背影行走", "visual_hook": "逆光剪影"},
            {"timestamp": "10s", "scene": "广场", "action": "万人跪拜", "visual_hook": "航拍大全景"},
        ],
    },
    {
        "title": "闪婚总裁：老公竟是隐藏大佬",
        "category": "女频",
        "sub_category": "甜宠",
        "hook_text": "相亲对象是个普通上班族？直到我看到他的黑卡...",
        "hook_type": "悬念",
        "emotion_curve": [
            {"time": "0s", "intensity": 0.3, "label": "平静"},
            {"time": "5s", "intensity": 0.6, "label": "好奇"},
            {"time": "12s", "intensity": 0.9, "label": "高潮"},
            {"time": "20s", "intensity": 0.5, "label": "释放"},
        ],
        "beat_points": [
            {"time": "2s", "type": "文案出现", "intensity": 0.6, "description": "反差文案"},
            {"time": "12s", "type": "特效", "intensity": 0.9, "description": "黑卡特写+金光"},
        ],
        "ctr": 0.052,
        "retention_3s": 0.85,
        "completion_rate": 0.38,
        "score": 90.0,
        "tags": ["甜宠", "总裁", "隐藏身份", "闪婚"],
        "asr_text": "妈给我安排的相亲对象，说是普通上班族。穿着朴素，开着十万块的车。直到那天，我不小心看到了他钱包里的黑卡...",
        "frame_descriptions": [
            {"timestamp": "0s", "scene": "咖啡厅", "action": "尴尬相亲", "visual_hook": "暖色日常感"},
            {"timestamp": "12s", "scene": "钱包特写", "action": "黑卡露出", "visual_hook": "金色光效+慢动作"},
        ],
    },
    {
        "title": "龙王驾到：岳母后悔跪求原谅",
        "category": "男频",
        "sub_category": "逆袭",
        "hook_text": "被岳母赶出家门的那天，一架直升机降落在楼下...",
        "hook_type": "冲突",
        "emotion_curve": [
            {"time": "0s", "intensity": 0.6, "label": "冲突"},
            {"time": "3s", "intensity": 0.4, "label": "低谷"},
            {"time": "8s", "intensity": 0.85, "label": "高潮"},
            {"time": "15s", "intensity": 0.5, "label": "释放"},
        ],
        "beat_points": [
            {"time": "0s", "type": "音乐节拍", "intensity": 0.8, "description": "紧张弦乐"},
            {"time": "8s", "type": "画面切换", "intensity": 1.0, "description": "直升机降落"},
        ],
        "ctr": 0.045,
        "retention_3s": 0.80,
        "completion_rate": 0.33,
        "score": 88.0,
        "tags": ["龙王", "打脸", "逆袭", "岳母"],
        "asr_text": "岳母把我的行李扔出门外，骂我是废物。我没有说话，只是默默拨通了一个号码。三分钟后，一架直升机降落在小区广场...",
        "frame_descriptions": [
            {"timestamp": "0s", "scene": "家门口", "action": "行李被扔", "visual_hook": "手持晃动感"},
            {"timestamp": "8s", "scene": "小区广场", "action": "直升机降落", "visual_hook": "航拍+慢动作"},
        ],
    },
    {
        "title": "穿越医妃：手握空间救全城",
        "category": "女频",
        "sub_category": "穿越",
        "hook_text": "穿越成废柴丑女？我的空间里有整个现代药房...",
        "hook_type": "反转",
        "emotion_curve": [
            {"time": "0s", "intensity": 0.5, "label": "困惑"},
            {"time": "5s", "intensity": 0.7, "label": "发现"},
            {"time": "12s", "intensity": 0.9, "label": "高潮"},
            {"time": "20s", "intensity": 0.6, "label": "释放"},
        ],
        "beat_points": [
            {"time": "0.5s", "type": "文案出现", "intensity": 0.7, "description": "穿越宣言"},
            {"time": "12s", "type": "特效", "intensity": 0.9, "description": "空间展开特效"},
        ],
        "ctr": 0.050,
        "retention_3s": 0.84,
        "completion_rate": 0.40,
        "score": 91.0,
        "tags": ["穿越", "医妃", "空间", "逆袭"],
        "asr_text": "一睁眼，我成了将军府的废柴丑女。所有人嘲笑我，直到瘟疫来袭，他们才知道，我的空间里装着整个现代药房...",
        "frame_descriptions": [
            {"timestamp": "0s", "scene": "古代房间", "action": "女主睁眼", "visual_hook": "模糊到清晰"},
            {"timestamp": "12s", "scene": "空间内", "action": "药房展示", "visual_hook": "3D环绕特效"},
        ],
    },
]


def seed_data():
    """灌入模拟数据"""
    init_db()
    db = SessionLocal()

    # 检查是否已有数据
    if db.query(HotRef).count() > 0:
        logger.info("数据已存在，跳过初始化")
        db.close()
        return

    for item in HOT_REFERENCES:
        ref = HotRef(**item)
        db.add(ref)

    db.commit()
    db.close()
    logger.info(f"已灌入 {len(HOT_REFERENCES)} 条爆款素材数据")


if __name__ == "__main__":
    seed_data()
