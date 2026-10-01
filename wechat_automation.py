# -*- coding: utf-8 -*-
"""Windows 微信 4.x GUI 自动化。
核心流程：确认/启动微信 -> 处理登录状态 -> 搜索 -> OCR -> 标题核验 -> 发送。
"""
from __future__ import annotations
import ctypes
import io
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pyautogui
import pyperclip
from PIL import Image, ImageGrab

try:
    import win32api, win32con, win32gui, win32clipboard, win32process
except ImportError as exc:
    raise RuntimeError("缺少 pywin32。请运行：py -3.11 -m pip install pywin32") from exc

from area_selector import RegionInfo, scale_region
from config import (
    CLICK_AFTER_TARGET,
    OCR_RETRY_COUNT,
    SECTION_LABELS,
    SEARCH_WAIT,
    SEND_WAIT,
    WECHAT_OPEN_TIMEOUT,
    WECHAT_TITLE_KEYWORDS,
)
from ocr_engine import OCREngine, OCRItem, normalize_text

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

Rect = Tuple[int, int, int, int]
LOGIN_OPEN_TEXTS = {normalize_text(x) for x in ("进入微信", "进入 WeChat")}
QR_TEXTS = {normalize_text(x) for x in ("扫码登录", "扫码", "二维码", "手机扫码", "使用手机微信扫码")}
WECHAT_PROCESS_NAMES = {"wechat.exe", "weixin.exe", "wechatexe", "wechatappex.exe", "wechatapp.exe"}
SEARCH_SHELL_PROCESSES = {"SearchHost.exe", "SearchApp.exe", "StartMenuExperienceHost.exe", "ShellExperienceHost.exe"}


class WeChatAutomation:
    def __init__(self, status_callback=None, ocr_retry_count: int = OCR_RETRY_COUNT, send_wait: float = SEND_WAIT):
        pyautogui.PAUSE = 0.08
        pyautogui.FAILSAFE = True
        self.status_callback = status_callback
        self.ocr = OCREngine()
        self.ocr_retry_count = max(1, int(ocr_retry_count))
        self.send_wait = max(0.2, float(send_wait))

    def status(self, text: str):
        if self.status_callback:
            try:
                self.status_callback(text)
            except Exception:
                pass

    @staticmethod
    def _visible_title(hwnd):
        try:
            return (win32gui.GetWindowText(hwnd) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _window_process_name(hwnd: int) -> str:
        """读取窗口所属进程的 EXE 名，避免把其他软件窗口误认成微信。"""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return ""
            handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_ulong(len(buf))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    return Path(buf.value).name.lower()
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            pass
        return ""

    def _is_wechat_process(self, hwnd: int) -> bool:
        return self._window_process_name(hwnd) in WECHAT_PROCESS_NAMES

    def find_window(self) -> Optional[int]:
        """只返回属于微信进程的顶层窗口；最小化状态也纳入。"""
        found = []

        def callback(hwnd, _):
            try:
                if win32gui.GetParent(hwnd):
                    return True
                visible = bool(win32gui.IsWindowVisible(hwnd))
                iconic = bool(win32gui.IsIconic(hwnd))
                if not visible and not iconic:
                    return True
                if not self._is_wechat_process(hwnd):
                    return True
                title = self._visible_title(hwnd)
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                found.append((hwnd, max(0, r-l)*max(0, b-t), title, visible, iconic))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        if not found:
            return None
        exact = [x for x in found if x[2] in ("微信", "WeChat")]
        if exact:
            exact.sort(key=lambda x: (1 if x[3] else 0, x[1]), reverse=True)
            return exact[0][0]
        found.sort(key=lambda x: x[1], reverse=True)
        return found[0][0]

    def find_login_window(self) -> Optional[int]:
        candidates = []

        def callback(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd) or win32gui.GetParent(hwnd):
                    return True
                if not self._is_wechat_process(hwnd):
                    return True
                title = self._visible_title(hwnd)
                if title not in ("微信", "WeChat"):
                    return True
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r-l, b-t
                if 260 <= w <= 900 and 300 <= h <= 900:
                    candidates.append((hwnd, w*h))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0] if candidates else None

    def activate(self, hwnd: int):
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise RuntimeError("微信窗口不存在或已关闭。")
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            try:
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:
            raise RuntimeError(f"无法把微信窗口带到桌面前台：{exc}") from exc
        deadline = time.time() + 3.5
        while time.time() < deadline:
            try:
                if win32gui.GetForegroundWindow() == hwnd and win32gui.IsWindowVisible(hwnd):
                    time.sleep(0.25)
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError("微信窗口没有成功进入桌面前台，为避免误操作，程序已停止。")

    def _ocr_window(self, hwnd):
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        image = ImageGrab.grab(bbox=(l, t, r, b))
        return image, self.ocr.read(image)

    @staticmethod
    def _green_login_button_present(image) -> bool:
        """登录小窗 OCR 漏字时，用绿色按钮颜色做二次保险；没有绿色按钮时绝不盲点。"""
        try:
            w, h = image.size
            crop = image.crop((int(w * 0.25), int(h * 0.56), int(w * 0.75), int(h * 0.86))).convert("RGB")
            hits = 0
            total = crop.width * crop.height
            for r, g, b in crop.getdata():
                if g > 150 and g > r * 1.35 and g > b * 1.12:
                    hits += 1
            return hits > max(180, total * 0.025)
        except Exception:
            return False

    def _click_login_button(self, hwnd) -> bool:
        self.activate(hwnd)
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        image, items = self._ocr_window(hwnd)
        for item in items:
            norm = normalize_text(item.text)
            if norm in LOGIN_OPEN_TEXTS or "进入微信" in norm:
                x1, y1, x2, y2 = item.box
                pyautogui.click(l + (x1 + x2) // 2, t + (y1 + y2) // 2)
                return True
        if self._green_login_button_present(image):
            pyautogui.click(l + (r - l) // 2, t + int((b - t) * 0.72))
            return True
        return False

    def _login_state(self, hwnd):
        image, items = self._ocr_window(hwnd)
        texts = {normalize_text(x.text) for x in items if x.text}
        if texts & QR_TEXTS or any("扫码" in x or "二维码" in x for x in texts):
            return "qr"
        if texts & LOGIN_OPEN_TEXTS or any("进入微信" in x for x in texts):
            return "enter"
        if self._green_login_button_present(image):
            return "enter"
        return "unknown"

    def _main_window_state(self, hwnd):
        """主窗口也检查一次二维码文字，防止扫码页被误当成已登录主页。"""
        try:
            _image, items = self._ocr_window(hwnd)
            texts = {normalize_text(x.text) for x in items if x.text}
            if texts & QR_TEXTS or any("扫码" in x or "二维码" in x for x in texts):
                return "qr"
        except Exception:
            pass
        return "main"

    def ensure_logged_in(self) -> int:
        login = self.find_login_window()
        if login:
            state = self._login_state(login)
            if state == "qr":
                raise RuntimeError("检测到微信扫码登录页面。请手动扫码登录后，再重新执行任务。")
            if state == "enter":
                self.status("发现微信登录小窗口，正在点击‘进入微信’……")
                if not self._click_login_button(login):
                    raise RuntimeError("发现微信登录窗口，但没有可靠找到‘进入微信’按钮；为避免误操作，程序已停止。")
                deadline = time.time() + 15
                while time.time() < deadline:
                    new_login = self.find_login_window()
                    if new_login:
                        state2 = self._login_state(new_login)
                        if state2 == "qr":
                            raise RuntimeError("点击‘进入微信’后进入扫码登录页面。需要手动扫码，本程序停止执行。")
                    main = self.find_window()
                    if main:
                        self.activate(main)
                        if self._main_window_state(main) == "qr":
                            raise RuntimeError("检测到微信扫码登录页面。请手动扫码登录后，再重新执行任务。")
                        return main
                    time.sleep(0.5)
                raise RuntimeError("点击‘进入微信’后未进入微信主界面。请检查微信是否已正常登录。")
            raise RuntimeError("检测到微信登录窗口，但无法可靠判断登录状态。请手动进入微信主界面后重试。")

        main = self.find_window()
        if main:
            self.activate(main)
            if self._main_window_state(main) == "qr":
                raise RuntimeError("检测到微信扫码登录页面。请手动扫码登录后，再重新执行任务。")
            return main
        return self.open_by_windows_search()


    @staticmethod
    def _foreground_process_name() -> str:
        try:
            user32=ctypes.windll.user32; kernel32=ctypes.windll.kernel32
            hwnd=user32.GetForegroundWindow()
            if not hwnd:return ""
            pid=ctypes.c_ulong(); user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            handle=kernel32.OpenProcess(0x1000,False,pid.value)
            if not handle:return ""
            try:
                buf=ctypes.create_unicode_buffer(520); size=ctypes.c_ulong(len(buf))
                if kernel32.QueryFullProcessImageNameW(handle,0,buf,ctypes.byref(size)):return Path(buf.value).name
            finally: kernel32.CloseHandle(handle)
        except Exception: pass
        return ""

    @staticmethod
    def _foreground_window() -> tuple[int,str,str]:
        try:
            hwnd=win32gui.GetForegroundWindow()
            title=(win32gui.GetWindowText(hwnd) or "").strip() if hwnd else ""
            return hwnd, WeChatAutomation._foreground_process_name(), title
        except Exception: return 0,"",""

    def _search_shell_ready(self, previous_hwnd: int, timeout: float = 6.0) -> bool:
        """确认搜索/开始菜单真正接管前台后才允许粘贴中文。"""
        allowed={x.lower() for x in SEARCH_SHELL_PROCESSES}
        deadline=time.time()+timeout
        while time.time()<deadline:
            hwnd,name,title=self._foreground_window()
            if hwnd and hwnd!=previous_hwnd:
                low=name.lower()
                if low in allowed or any(k in title for k in ("搜索","Search","开始","Start")):
                    return True
            time.sleep(0.15)
        return False

    @staticmethod
    def _wait_search_animation(seconds: float = 3.6):
        """给 Win+S / 开始菜单留出完整的弹出动画时间。"""
        time.sleep(max(3.0,float(seconds)))

    def _start_from_start_apps(self) -> bool:
        """通过 Windows StartApps 获取微信 AppID 后启动。"""
        try:
            import subprocess
            cmd=["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",
                 "$x=Get-StartApps | Where-Object {$_.Name -match '微信|WeChat|Weixin'} | Select-Object -First 1; if($x){$x.AppID}"]
            proc=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="ignore",timeout=8)
            appid=(proc.stdout or "").strip().splitlines()
            appid=appid[0].strip() if appid else ""
            if appid:
                subprocess.Popen(["explorer.exe",f"shell:AppsFolder\\{appid}"])
                self.status("已通过 Windows 应用列表找到微信，正在启动……")
                return True
        except Exception:
            pass
        return False

    def open_by_windows_search(self) -> int:
        """先恢复已有微信；没有时用 Win+S，再用开始菜单和 StartApps 后备。"""
        existing=self.find_window()
        if existing:return self.ensure_logged_in()
        login=self.find_login_window()
        if login:return self.ensure_logged_in()
        last_error=None
        for attempt in range(1,3):
            try:
                previous,_name,_title=self._foreground_window()
                self.status(f"正在打开 Windows 搜索（第 {attempt}/2 次），等待搜索动画结束……")
                pyautogui.hotkey("win","s")
                self._wait_search_animation(3.6)
                if not self._search_shell_ready(previous,3.0):
                    raise RuntimeError("Win+S 后没有确认系统搜索窗口进入前台，因此没有输入或回车。")
                pyperclip.copy("微信")
                pyautogui.hotkey("ctrl","v")
                time.sleep(1.2)
                pyautogui.press("enter")
                deadline=time.time()+WECHAT_OPEN_TIMEOUT
                while time.time()<deadline:
                    login=self.find_login_window()
                    if login:return self.ensure_logged_in()
                    main=self.find_window()
                    if main:return self.ensure_logged_in()
                    time.sleep(0.45)
            except Exception as exc:
                last_error=exc
                self.status(f"Win+S 尝试未成功：{exc}")
            time.sleep(0.6)
        try:
            previous,_name,_title=self._foreground_window()
            self.status("Win+S 未成功，改用 Windows 开始菜单搜索……")
            pyautogui.press("win")
            self._wait_search_animation(3.0)
            if not self._search_shell_ready(previous,3.0):
                raise RuntimeError("开始菜单后没有确认搜索区域进入前台，因此没有输入或回车。")
            pyperclip.copy("微信")
            pyautogui.hotkey("ctrl","v")
            time.sleep(1.0)
            pyautogui.press("enter")
            deadline=time.time()+WECHAT_OPEN_TIMEOUT
            while time.time()<deadline:
                login=self.find_login_window()
                if login:return self.ensure_logged_in()
                main=self.find_window()
                if main:return self.ensure_logged_in()
                time.sleep(0.45)
        except Exception as exc:
            last_error=exc
        try:
            if self._start_from_start_apps():
                candidate=self._wait_for_wechat_window(WECHAT_OPEN_TIMEOUT)
                if candidate:return self.ensure_logged_in()
        except Exception as exc:
            last_error=exc
        detail=f"\\n最后错误：{last_error}" if last_error else ""
        raise RuntimeError("无法自动启动并进入电脑版微信。\n\n为避免误操作，程序只有在确认搜索/开始菜单获得前台后才会输入‘微信’并回车。"+detail)

    def client_rect(self, hwnd: int) -> Rect:
        _l, _t, r, b = win32gui.GetClientRect(hwnd)
        sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
        return sx, sy, r, b

    def screen_rect_from_region(self, hwnd: int, region: RegionInfo) -> Rect:
        left, top, cw, ch = self.client_rect(hwnd)
        rx, ry, rw, rh = scale_region(region, cw, ch)
        return left + rx, top + ry, rw, rh

    def search(self, target: str) -> int:
        target = (target or "").strip()
        if not target:
            raise ValueError("目标名称不能为空。")
        hwnd = self.ensure_logged_in()
        self.activate(hwnd)
        self.status(f"正在搜索：{target}")
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.55)
        pyautogui.hotkey("ctrl", "a")
        pyperclip.copy(target)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(SEARCH_WAIT)
        login = self.find_login_window()
        if login:
            return self.ensure_logged_in()
        return hwnd

    def capture_region(self, hwnd: int, region: RegionInfo):
        x, y, w, h = self.screen_rect_from_region(hwnd, region)
        return ImageGrab.grab(bbox=(x, y, x + w, y + h))

    def inspect_region(self, hwnd: int, region: RegionInfo) -> List[OCRItem]:
        image = self.capture_region(hwnd, region)
        return self.ocr.assign_sections(self.ocr.read(image), SECTION_LABELS)

    def locate_target(self, hwnd: int, region: RegionInfo, target: str, target_type: str = "auto"):
        for attempt in range(1, self.ocr_retry_count + 1):
            self.status(f"OCR 识别搜索结果（第 {attempt}/{self.ocr_retry_count} 次）……")
            items = self.ocr.assign_sections(self.ocr.read(self.capture_region(hwnd, region)), SECTION_LABELS)
            candidates = self.ocr.candidates(items, target, target_type)
            if candidates:
                best, score = candidates[0]
                exactish = [
                    x for x in candidates
                    if normalize_text(x[0].text) == normalize_text(best.text) and x[1] >= score - 5
                ]
                if len(exactish) > 1 and target_type == "auto":
                    sections = ", ".join(dict.fromkeys(x[0].section for x in exactish))
                    raise RuntimeError(
                        f"搜索结果里存在多个接近的同名目标‘{best.text}’（分类：{sections}）。请明确选择‘群聊’或‘联系人’。"
                    )
                x, y, _, _ = self.screen_rect_from_region(hwnd, region)
                bx1, by1, bx2, by2 = best.box
                return x + (bx1 + bx2) // 2, y + (by1 + by2) // 2, best, score
            time.sleep(0.7)
        return None

    def click_target(self, hwnd, region, target, target_type="auto"):
        result = self.locate_target(hwnd, region, target, target_type)
        if not result:
            raise RuntimeError(f"OCR 没有在指定区域找到‘{target}’。请检查搜索区域和目标类型。")
        cx, cy, item, score = result
        self.status(f"识别到：{item.text} | 分类：{item.section} | 评分：{score:.1f}")
        pyautogui.click(cx, cy)
        time.sleep(CLICK_AFTER_TARGET)
        return item, score

    @staticmethod
    def _normalize_chat_title(text: str) -> str:
        raw = (text or "").strip()
        raw = re.sub(r"\s*[\(（]\s*\d+\s*[\)）]\s*$", "", raw)
        return normalize_text(raw)

    def verify_target(self, hwnd, target, regions: Sequence[RegionInfo]) -> bool:
        if not regions:
            return True
        target_norm = self._normalize_chat_title(target)
        for idx, region in enumerate(regions, 1):
            try:
                for item in self.ocr.read(self.capture_region(hwnd, region)):
                    raw_norm = self._normalize_chat_title(item.text)
                    sim = self.ocr._similarity(item.text, target)
                    if raw_norm == target_norm or sim >= 0.86:
                        self.status(f"目标核验通过：标题框 {idx} 识别到‘{item.text}’。")
                        return True
            except Exception:
                pass
        self.status(f"目标核验未通过：标题框中没有发现‘{target}’。")
        return False

    def click_message_input(self, hwnd):
        left, top, width, height = self.client_rect(hwnd)
        # 不再保存/框选输入区；沿用微信 4.x 常见布局的安全默认点。
        pyautogui.click(left + int(width * 0.70), top + int(height * 0.88))
        time.sleep(0.25)

    def send_text(self, hwnd, text):
        if not text:
            return
        self.click_message_input(hwnd)
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.25)
        pyautogui.press("enter")
        time.sleep(self.send_wait)

    @staticmethod
    def set_clipboard_image(image_path):
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        output = io.BytesIO()
        image.save(output, "BMP")
        data = output.getvalue()[14:]
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, data)
        finally:
            win32clipboard.CloseClipboard()

    def send_image(self, hwnd, image_path):
        self.click_message_input(hwnd)
        self.set_clipboard_image(image_path)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(1.1)
        pyautogui.press("enter")
        time.sleep(self.send_wait)

    def run_single(self, target_info, search_region, verify_regions=None, verify_target_enabled=True, continue_on_error=False):
        name = str(target_info.get("name", "")).strip()
        target_type = str(target_info.get("type", "auto"))
        text = str(target_info.get("message", "") or "")
        images = list(target_info.get("images", []))
        if not name:
            raise RuntimeError("目标名称不能为空。")
        if not text and not images:
            raise RuntimeError(f"目标‘{name}’没有配置文字或图片。")
        hwnd = self.search(name)
        self.click_target(hwnd, search_region, name, target_type)
        verify_regions = list(verify_regions or [])
        if verify_target_enabled and verify_regions and not self.verify_target(hwnd, name, verify_regions):
            raise RuntimeError(f"目标核验失败，已停止向‘{name}’发送，以避免发错人/群。")
        if target_info.get("send_order", "text_then_images") == "images_then_text":
            for path in images:
                self.send_image(hwnd, path)
            self.send_text(hwnd, text)
        else:
            self.send_text(hwnd, text)
            for path in images:
                self.send_image(hwnd, path)
        return {"target": name, "ok": True}
