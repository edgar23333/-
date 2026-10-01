# -*- coding: utf-8 -*-
"""微信自动定时发送助手 V15.0：配置、路径与默认值。"""
from __future__ import annotations
import sys
from pathlib import Path

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_DIR / "config.json"
TASKS_FILE = DATA_DIR / "tasks.json"
LOG_FILE = DATA_DIR / "app.log"

APP_TITLE = "微信自动定时发送助手 V15.0"
APP_VERSION = "V15.0 Stable"
APP_AUTHOR = "Edgar Jingxiu"
APP_EMAIL = "sunzhuojian13@gmail.com"
APP_AVATAR = BASE_DIR / "assets" / "edgar_avatar.png"
APP_ICON = BASE_DIR / "assets" / "edgar_avatar.ico"

# 运行时资源搜索：EXE目录优先，其次 PyInstaller 内部目录，再到源码目录。
try:
    from resource_utils import asset_path
    _avatar = asset_path("assets/edgar_avatar.png")
    _icon = asset_path("assets/edgar_avatar.ico")
    if _avatar: APP_AVATAR = _avatar
    if _icon: APP_ICON = _icon
except Exception:
    pass

WECHAT_TITLE_KEYWORDS = ("微信", "WeChat")
WECHAT_OPEN_TIMEOUT = 25
SEARCH_WAIT = 1.4
OCR_RETRY_COUNT = 5
OCR_RETRY_INTERVAL = 0.8
CLICK_AFTER_TARGET = 1.2
SEND_WAIT = 0.9

SECTION_LABELS = (
    "最常使用", "联系人", "群聊", "群组", "公众号",
    "最近使用", "最近聊天", "新的朋友", "标签",
)

DEFAULT_CONFIG = {
    "last_task_id": "",
    "default_use_system_scheduler": False,
    "default_auto_shutdown": False,
    "theme": "浅色",
    "banner_image": "",
    "ocr_retry_count": OCR_RETRY_COUNT,
    "send_wait": SEND_WAIT,
}

DEFAULT_TARGET = {
    "name": "",
    "type": "auto",
    "message": "",
    "images": [],
    "send_order": "text_then_images",
    "schedule": {"mode": "now", "datetime": ""},
    "scheduler_mode": "app",
    "auto_shutdown": False,
    "enabled": True,
    "system_task_name": "",
}

DEFAULT_TASK = {
    "id": "",
    "name": "新任务",
    "enabled": True,
    "targets": [],
    "search_region": None,
    "verify_regions": [],
    "verify_target": True,
    "continue_on_error": False,
}
