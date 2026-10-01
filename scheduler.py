# -*- coding: utf-8 -*-
"""应用内多目标定时调度：每个目标可以拥有自己的时间。"""
from __future__ import annotations
from datetime import datetime
import threading
from typing import Callable, Optional

class MultiTargetScheduler:
    def __init__(self, execute_callback: Callable, status_callback=None):
        self.execute_callback = execute_callback
        self.status_callback = status_callback
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.running = False

    def _status(self, text: str):
        if self.status_callback:
            try:
                self.status_callback(text)
            except Exception:
                pass

    def start(self, jobs: list[tuple[str, datetime]]):
        self.stop()
        clean = [(str(job_id), when) for job_id, when in jobs if isinstance(when, datetime) and when > datetime.now()]
        if not clean:
            raise ValueError("没有可启动的未来定时目标。")
        clean.sort(key=lambda x: x[1])
        self.stop_event = threading.Event()
        self.running = True
        event = self.stop_event
        self.thread = threading.Thread(target=self._worker, args=(clean, event), daemon=True, name="multi-schedule-worker")
        self.thread.start()

    def _worker(self, jobs, event):
        pending = list(jobs)
        try:
            while pending and not event.is_set():
                pending.sort(key=lambda x: x[1])
                job_id, when = pending[0]
                remain = (when - datetime.now()).total_seconds()
                if remain > 0:
                    if remain >= 60:
                        self._status(f"应用内定时：下一个目标 {when:%m-%d %H:%M}（约 {int(remain // 60)} 分钟后）")
                    else:
                        self._status(f"应用内定时：下一个目标 {when:%H:%M:%S}（约 {max(0, int(remain))} 秒后）")
                    event.wait(min(1.0, remain))
                    continue
                self._status(f"定时时间到：{when:%Y-%m-%d %H:%M:%S}，开始执行目标 {job_id}。")
                try:
                    self.execute_callback(job_id)
                finally:
                    pending.pop(0)
            if not pending and not event.is_set():
                self._status("全部应用内定时目标已处理完成。")
        finally:
            self.running = False
            self.thread = None

    def stop(self):
        self.stop_event.set()
        self.running = False
        self.thread = None
