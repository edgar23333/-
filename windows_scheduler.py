# -*- coding: utf-8 -*-
"""Windows 任务计划：每个目标独立创建一次性任务。"""
from __future__ import annotations
from datetime import datetime
import getpass, os, subprocess, tempfile
from pathlib import Path

def _xml_escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))

def create_one_shot_task(task_id: str, target_index: int, when: datetime, exe_path: str) -> str:
    if os.name != "nt":
        raise RuntimeError("此功能仅支持 Windows。")
    if when <= datetime.now():
        raise ValueError("定时时间必须晚于当前时间。")
    task_name = f"WeChatAutoSender_{task_id[:8]}_{target_index + 1:03d}"
    exe_path = os.path.abspath(exe_path)
    user_domain = os.environ.get("USERDOMAIN") or ""
    user_name = os.environ.get("USERNAME") or getpass.getuser()
    author_id = (user_domain + "\\" + user_name) if user_domain else user_name
    xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>微信自动定时发送助手 V13.0 目标定时任务</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>{when:%Y-%m-%dT%H:%M:%S}</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{_xml_escape(author_id)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <WakeToRun>true</WakeToRun>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml_escape(exe_path)}</Command>
      <Arguments>--run-scheduled --task-id "{_xml_escape(task_id)}" --target-index "{target_index}"</Arguments>
      <WorkingDirectory>{_xml_escape(str(Path(exe_path).parent))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as f:
        xml_path = f.name
        f.write(xml.encode("utf-16"))
    try:
        proc = subprocess.run(["schtasks", "/Create", "/TN", task_name, "/XML", xml_path, "/F"], capture_output=True, text=True, encoding="mbcs", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "schtasks 创建任务失败").strip())
    finally:
        try: os.unlink(xml_path)
        except OSError: pass
    return task_name

def delete_task(task_name: str):
    if not task_name: return
    proc = subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], capture_output=True, text=True, encoding="mbcs", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if "找不到" not in err and "cannot find" not in err.lower():
            raise RuntimeError(err or "删除系统定时任务失败。")
