# -*- coding: utf-8 -*-
"""Windows 系统定时任务的无界面执行入口。一次只执行一个目标。"""
from __future__ import annotations
import json, logging, os, subprocess
from datetime import datetime
from config import CONFIG_FILE, TASKS_FILE, DEFAULT_CONFIG, LOG_FILE
from area_selector import RegionInfo
from wechat_automation import WeChatAutomation
from windows_scheduler import delete_task

def load_json(path, default):
    try:
        if path.exists(): return json.loads(path.read_text("utf-8"))
    except Exception: logging.exception("读取 JSON 失败: %s", path)
    return default

def run_task(task_id: str, target_index: int):
    logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", encoding="utf-8")
    settings = load_json(CONFIG_FILE, DEFAULT_CONFIG.copy())
    tasks = load_json(TASKS_FILE, [])
    task = next((x for x in tasks if str(x.get("id")) == str(task_id)), None)
    if not task: raise RuntimeError(f"找不到任务：{task_id}")
    targets = task.get("targets", [])
    if target_index < 0 or target_index >= len(targets): raise RuntimeError(f"目标序号无效：{target_index + 1}")
    target = dict(targets[target_index])
    if not target.get("enabled", True):
        logging.info("目标已禁用，跳过：%s/%s", task_id, target_index)
        return
    search_region = task.get("search_region")
    if not search_region: raise RuntimeError("任务没有配置搜索结果 OCR 区域。")
    images = list(target.get("images", []))
    missing = [p for p in images if not os.path.isfile(p)]
    if missing: raise RuntimeError(f"发送前发现图片文件不存在：{missing}")
    automation = WeChatAutomation(
        ocr_retry_count=int(settings.get("ocr_retry_count", 5)),
        send_wait=float(settings.get("send_wait", 0.9)),
    )
    logging.info("系统任务开始：task=%s target=%s/%s %s", task_id, target_index + 1, len(targets), target.get("name", ""))
    results = automation.run_single(
        target_info=target,
        search_region=RegionInfo.from_dict(search_region),
        verify_regions=[RegionInfo.from_dict(x) for x in task.get("verify_regions", [])],
        verify_target_enabled=bool(task.get("verify_target", True)),
        continue_on_error=bool(task.get("continue_on_error", False)),
    )
    logging.info("系统任务结束：%s", results)
    system_name = target.get("system_task_name", "")
    try:
        tasks = load_json(TASKS_FILE, [])
        for item in tasks:
            if str(item.get("id")) == str(task_id):
                if target_index < len(item.get("targets", [])):
                    item["targets"][target_index]["schedule"] = {"mode": "now", "datetime": ""}
                    item["targets"][target_index]["scheduler_mode"] = "app"
                    item["targets"][target_index]["system_task_name"] = ""
                break
        TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), "utf-8")
    except Exception: logging.exception("更新系统任务状态失败")
    if system_name:
        try: delete_task(system_name)
        except Exception: logging.exception("删除已完成 Windows 系统任务失败")
    if target.get("auto_shutdown"):
        logging.info("目标配置了发送完成自动关机，30 秒后关机。")
        subprocess.Popen(["shutdown", "/s", "/t", "30", "/d", "p:0:0"])

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--target-index", required=True, type=int)
    args = parser.parse_args()
    try: run_task(args.task_id, args.target_index)
    except Exception: logging.exception("系统定时任务失败"); raise
