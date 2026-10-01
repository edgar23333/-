# -*- coding: utf-8 -*-
"""主 Tk 线程使用的全屏单/多框选择器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import ImageGrab, ImageTk
import tkinter as tk

Rect = Tuple[int, int, int, int]

try:
    import ctypes
except Exception:  # pragma: no cover
    ctypes = None


@dataclass
class RegionInfo:
    """相对于微信客户区左上角的区域。"""

    x: int
    y: int
    width: int
    height: int
    base_client_width: int
    base_client_height: int

    def as_tuple(self) -> Rect:
        return self.x, self.y, self.width, self.height

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "base_client_width": self.base_client_width,
            "base_client_height": self.base_client_height,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RegionInfo":
        return cls(
            int(data["x"]),
            int(data["y"]),
            int(data["width"]),
            int(data["height"]),
            int(data.get("base_client_width", 1)),
            int(data.get("base_client_height", 1)),
        )


def virtual_screen_rect() -> Rect:
    if ctypes is not None and hasattr(ctypes, "windll"):
        user32 = ctypes.windll.user32
        return (
            int(user32.GetSystemMetrics(76)),
            int(user32.GetSystemMetrics(77)),
            int(user32.GetSystemMetrics(78)),
            int(user32.GetSystemMetrics(79)),
        )
    return 0, 0, 1920, 1080


class MultiRegionSelector:
    """一次可框选多个区域；回车完成，ESC 取消。"""

    def __init__(
        self,
        parent: tk.Misc,
        client_rect: Rect,
        title_text: str,
        instruction: str,
        max_regions: int = 8,
    ):
        self.parent = parent
        self.client_rect = client_rect
        self.title_text = title_text
        self.instruction = instruction
        self.max_regions = max(1, int(max_regions))
        self.window = None
        self.canvas = None
        self.photo = None
        self.virtual_rect = None
        self.start = None
        self.temp_rect_id = None
        self.rect_ids: List[int] = []
        self.results: List[RegionInfo] = []
        self.cancelled = True
        self.info_text_id = None

    def select(self) -> Optional[List[RegionInfo]]:
        self.virtual_rect = virtual_screen_rect()
        vx, vy, _, _ = self.virtual_rect

        try:
            shot = ImageGrab.grab(all_screens=True)
        except TypeError:
            shot = ImageGrab.grab()
            vx, vy = 0, 0
            self.virtual_rect = (0, 0, shot.width, shot.height)

        self.window = tk.Toplevel(self.parent)
        self.window.title(self.title_text)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.geometry(f"{shot.width}x{shot.height}{vx:+d}{vy:+d}")
        self.window.configure(cursor="crosshair")
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)

        self.canvas = tk.Canvas(
            self.window,
            width=shot.width,
            height=shot.height,
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)
        self.photo = ImageTk.PhotoImage(shot, master=self.window)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")

        self.canvas.create_rectangle(0, 0, min(1250, shot.width), 80, fill="#111111", outline="")
        self.canvas.create_text(
            18,
            12,
            text=self.title_text,
            fill="white",
            anchor="nw",
            font=("Microsoft YaHei UI", 16, "bold"),
        )
        self.info_text_id = self.canvas.create_text(
            18,
            44,
            text=self.instruction,
            fill="#8ee7ff",
            anchor="nw",
            font=("Microsoft YaHei UI", 10),
        )

        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        self.window.bind("<Escape>", lambda _e: self.cancel())
        self.window.bind("<Return>", lambda _e: self.finish())
        self.window.focus_force()
        self.window.grab_set()
        self.parent.wait_window(self.window)
        return list(self.results) if not self.cancelled else None

    def cancel(self):
        self.cancelled = True
        self.results = []
        if self.window and self.window.winfo_exists():
            try:
                self.window.grab_release()
            except Exception:
                pass
            self.window.destroy()

    def finish(self):
        if not self.results:
            self.cancel()
            return
        self.cancelled = False
        if self.window and self.window.winfo_exists():
            try:
                self.window.grab_release()
            except Exception:
                pass
            self.window.destroy()

    def on_down(self, event):
        if len(self.results) >= self.max_regions:
            return
        self.start = (event.x, event.y)
        if self.temp_rect_id is not None:
            self.canvas.delete(self.temp_rect_id)
        self.temp_rect_id = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#00e5ff",
            width=3,
        )

    def on_move(self, event):
        if self.start is None or self.temp_rect_id is None:
            return
        x0, y0 = self.start
        self.canvas.coords(self.temp_rect_id, x0, y0, event.x, event.y)

    def on_up(self, event):
        if self.start is None:
            return
        x0, y0 = self.start
        x1, y1 = event.x, event.y
        self.start = None

        left = min(x0, x1)
        top = min(y0, y1)
        right = max(x0, x1)
        bottom = max(y0, y1)
        if right - left < 30 or bottom - top < 30:
            if self.temp_rect_id is not None:
                self.canvas.delete(self.temp_rect_id)
                self.temp_rect_id = None
            return

        vx, vy, _, _ = self.virtual_rect
        abs_left = vx + left
        abs_top = vy + top
        rx = abs_left - self.client_rect[0]
        ry = abs_top - self.client_rect[1]
        rw = right - left
        rh = bottom - top

        wx_left, wx_top, wx_w, wx_h = self.client_rect
        ix1 = max(0, rx)
        iy1 = max(0, ry)
        ix2 = min(wx_w, rx + rw)
        iy2 = min(wx_h, ry + rh)
        width = ix2 - ix1
        height = iy2 - iy1
        if width < 30 or height < 30:
            if self.temp_rect_id is not None:
                self.canvas.delete(self.temp_rect_id)
                self.temp_rect_id = None
            return

        region = RegionInfo(
            int(ix1),
            int(iy1),
            int(width),
            int(height),
            int(wx_w),
            int(wx_h),
        )
        self.results.append(region)
        if self.temp_rect_id is not None:
            rect_id = self.temp_rect_id
            self.rect_ids.append(rect_id)
            self.canvas.itemconfigure(rect_id, outline="#00ff66", width=4)
            # 编号放到框的左上角。
            self.canvas.create_rectangle(left, top, left + 70, top + 28, fill="#111111", outline="")
            self.canvas.create_text(
                left + 8,
                top + 5,
                text=f"区域 {len(self.results)}",
                fill="#00ff66",
                anchor="nw",
                font=("Microsoft YaHei UI", 10, "bold"),
            )
            self.temp_rect_id = None

        self._update_hint()

        if len(self.results) >= self.max_regions:
            self._update_hint(f"已达到最多 {self.max_regions} 个区域，按回车完成。")

    def _update_hint(self, extra: str = ""):
        base = f"已框选 {len(self.results)} 个区域。继续拖框；按 Enter 完成，ESC 取消。"
        if extra:
            base = extra
        if self.info_text_id is not None:
            self.canvas.itemconfigure(self.info_text_id, text=base)


class AreaSelector:
    """兼容旧调用：单框选择。"""

    def __init__(self, parent: tk.Misc, client_rect: Rect):
        self.parent = parent
        self.client_rect = client_rect

    def select(self) -> Optional[RegionInfo]:
        selector = MultiRegionSelector(
            self.parent,
            self.client_rect,
            "框选 OCR 搜索结果区域",
            "拖动鼠标框选一个搜索结果区域。松开后按 Enter 完成；ESC 取消。",
            max_regions=1,
        )
        result = selector.select()
        return result[0] if result else None


def scale_region(region: RegionInfo, current_client_width: int, current_client_height: int) -> Rect:
    bw = max(1, int(region.base_client_width))
    bh = max(1, int(region.base_client_height))
    sx = current_client_width / bw
    sy = current_client_height / bh
    x = round(region.x * sx)
    y = round(region.y * sy)
    w = round(region.width * sx)
    h = round(region.height * sy)
    x = max(0, min(x, max(0, current_client_width - 1)))
    y = max(0, min(y, max(0, current_client_height - 1)))
    w = max(1, min(w, max(1, current_client_width - x)))
    h = max(1, min(h, max(1, current_client_height - y)))
    return x, y, w, h
