# -*- coding: utf-8 -*-
"""微信自动定时发送助手 V13.0。"""
from __future__ import annotations
import ctypes, json, logging, os, sys, threading, uuid
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except Exception: pass
from area_selector import AreaSelector, MultiRegionSelector, RegionInfo
from calendar_widget import MonthCalendar
from config import *
from layout_helper import suggest_regions
from scheduler import MultiTargetScheduler
from wechat_automation import WeChatAutomation
from windows_scheduler import create_one_shot_task, delete_task
from resource_utils import load_avatar_image

logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", encoding="utf-8")

def new_task(name="新任务"):
    task=json.loads(json.dumps(DEFAULT_TASK,ensure_ascii=False)); task["id"]=uuid.uuid4().hex; task["name"]=name; return task

def load_tasks_file():
    try:
        if TASKS_FILE.exists():
            data=json.loads(TASKS_FILE.read_text("utf-8")); return data if isinstance(data,list) else []
    except Exception: logging.exception("读取任务列表失败")
    return []

def save_tasks_file(tasks):
    TASKS_FILE.parent.mkdir(parents=True,exist_ok=True); tmp=TASKS_FILE.with_suffix(".tmp"); tmp.write_text(json.dumps(tasks,ensure_ascii=False,indent=2),"utf-8"); tmp.replace(TASKS_FILE)

def load_settings():
    data=dict(DEFAULT_CONFIG)
    try:
        if CONFIG_FILE.exists():
            loaded=json.loads(CONFIG_FILE.read_text("utf-8"));
            if isinstance(loaded,dict): data.update(loaded)
    except Exception: logging.exception("读取配置失败")
    return data

def save_settings(data): CONFIG_FILE.parent.mkdir(parents=True,exist_ok=True); CONFIG_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),"utf-8")

def migrate_tasks(tasks):
    """把旧 V5/V7 的任务级消息/时间迁移到每个目标，删除输入区概念。"""
    changed=False
    for task in tasks:
        old_message=str(task.get("message","") or ""); old_images=list(task.get("images",[]) or []); old_schedule=task.get("schedule") or {"mode":"now","datetime":""}; old_mode=task.get("scheduler_mode","app"); old_shutdown=bool(task.get("auto_shutdown",False))
        targets=task.get("targets",[]) or []
        new_targets=[]
        for t in targets:
            nt=json.loads(json.dumps(DEFAULT_TARGET,ensure_ascii=False)); nt.update(t)
            if not nt.get("message") and old_message: nt["message"]=old_message; changed=True
            if not nt.get("images") and old_images: nt["images"]=list(old_images); changed=True
            if nt.get("schedule",{}).get("mode") in (None,"now") and old_schedule.get("mode")=="once": nt["schedule"]=dict(old_schedule); nt["scheduler_mode"]=old_mode; nt["auto_shutdown"]=old_shutdown; changed=True
            new_targets.append(nt)
        if targets!=new_targets: task["targets"]=new_targets
        for key in ("message","images","schedule","scheduler_mode","auto_shutdown","input_region","system_task_name"):
            if key in task and key in ("input_region","system_task_name"): task.pop(key,None); changed=True
        task.setdefault("search_region",None); task.setdefault("verify_regions",[]); task.setdefault("verify_target",True); task.setdefault("continue_on_error",False)
    return tasks,changed

THEMES={
    "浅色":{"bg":"#f4f7fb","card":"#ffffff","fg":"#1f2937","muted":"#64748b","accent":"#2563eb"},
    "蓝色":{"bg":"#edf5ff","card":"#ffffff","fg":"#16324f","muted":"#55718c","accent":"#0b6cff"},
    "深色":{"bg":"#20252e","card":"#2a303a","fg":"#f3f4f6","muted":"#b7c0cc","accent":"#60a5fa"},
}

class ScrollableFrame(ttk.Frame):
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,highlightthickness=0,borderwidth=0)
        self.scrollbar=ttk.Scrollbar(self,orient="vertical",command=self.canvas.yview)
        self.inner=ttk.Frame(self.canvas)
        self.win=self.canvas.create_window((0,0),window=self.inner,anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left",fill="both",expand=True)
        self.scrollbar.pack(side="right",fill="y")
        self.inner.bind("<Configure>",lambda e:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(self.win,width=e.width))
        self.canvas.bind("<Enter>",lambda e:self.canvas.bind_all("<MouseWheel>",self._wheel,add="+"))
        self.canvas.bind("<Leave>",lambda e:self.canvas.unbind_all("<MouseWheel>"))
    def _wheel(self,event):
        delta=int(-event.delta/120) if event.delta else 0
        if delta: self.canvas.yview_scroll(delta,"units")

class AboutDialog(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent); self.title("关于 / 制作信息"); self.geometry("500x620"); self.minsize(440,500); self.transient(parent); self.grab_set(); self.outer=None
        self.bind("<Escape>",lambda e:self.destroy())
        outer=ScrollableFrame(self); self.outer=outer
        self.bind_all("<MouseWheel>", self._about_wheel, add="+")
        self.bind("<Destroy>", lambda e: self._about_unbind() if e.widget is self else None, add="+"); outer.pack(fill="both",expand=True); f=outer.inner; f.configure(padding=26)
        try:
            from PIL import ImageTk
            img=load_avatar_image()
            if img is not None:
                img.thumbnail((120,120))
                self.photo=ImageTk.PhotoImage(img,master=self)
                ttk.Label(f,image=self.photo).pack(pady=(4,12))
        except Exception:
            pass
        ttk.Label(f,text=APP_AUTHOR,font=("Microsoft YaHei UI",22,"bold")).pack(); ttk.Label(f,text=APP_TITLE,font=("Microsoft YaHei UI",15,"bold")).pack(pady=(6,2)); ttk.Label(f,text=APP_VERSION,foreground="#6b7280").pack(); ttk.Separator(f).pack(fill="x",pady=18)
        for x in (f"制作：{APP_AUTHOR}",f"邮箱：{APP_EMAIL}","核心：多目标独立消息 / 独立时间 / OCR 核验 / Windows 系统计划","标题核验默认只使用 1 个用户框选区域；群聊标题会自动忽略末尾人数，例如‘工作群 (8)’会按‘工作群’核验。","AI 自动聊天仍为实验性功能，不进入稳定发送链路。","本程序不会代替微信扫码登录；检测到扫码页面会停止任务。微信已最小化时会先恢复；微信未运行时先尝试 Win+S，等待系统搜索动画结束后才输入“微信”。","制作信息窗口支持鼠标滚轮上下滚动。"):
            ttk.Label(f,text=x,wraplength=410).pack(anchor="w",pady=5)
        ttk.Label(f,text="V13.0 修改记录",font=("Microsoft YaHei UI",12,"bold")).pack(anchor="w",pady=(18,6))
        ttk.Label(f,text="• 登录页：识别‘进入微信’则自动点击；识别扫码页则停止并提示。\n• 最小化微信先恢复；未运行时优先 Win+S，并等待动画完成后再输入“微信”。\n• 搜索结果与聊天标题分开框选；两者允许重叠。\n• 搜索结果建议框保持稳定，聊天标题建议框向右、向上收窄并给长名称留余量。\n• 每个联系人/群单独设置文字、图片和时间。\n• 每个目标可独立使用 Windows 任务计划。\n• 日历设置支持滚轮与 1 分钟精度。",wraplength=410).pack(anchor="w")
        ttk.Button(f,text="关闭",command=self.destroy).pack(pady=22)

    def _about_wheel(self,event):
        try:
            if self.outer and self.outer.winfo_exists():
                self.outer.canvas.yview_scroll(int(-event.delta/120),"units")
        except Exception:
            pass
    def _about_unbind(self):
        try:
            self.unbind_all("<MouseWheel>")
        except Exception:
            pass

class ScheduleDialog(tk.Toplevel):
    def __init__(self,parent,current=None):
        super().__init__(parent); self.title("设置目标发送时间"); self.geometry("640x760"); self.minsize(560,620); self.transient(parent); self.grab_set(); self.result=None; current=current or {}; sched=current.get("schedule",{})
        existing=sched.get("datetime","")
        try: dt=datetime.strptime(existing,"%Y-%m-%d %H:%M:%S")
        except Exception: dt=(datetime.now()+timedelta(minutes=10)).replace(second=0,microsecond=0)
        self.selected_date=dt.date(); self.hour_var=tk.IntVar(value=dt.hour); self.minute_var=tk.IntVar(value=dt.minute); self.once_var=tk.BooleanVar(value=sched.get("mode")=="once"); self.system_var=tk.BooleanVar(value=current.get("scheduler_mode")=="system"); self.shutdown_var=tk.BooleanVar(value=bool(current.get("auto_shutdown",False)))
        sf=ScrollableFrame(self); sf.pack(fill="both",expand=True); f=sf.inner; f.configure(padding=18)
        ttk.Label(f,text="定时发送",font=("Microsoft YaHei UI",20,"bold")).pack(anchor="w"); ttk.Label(f,text="每个目标都可以有自己的时间。分钟精度为 1 分钟，整个设置页可以鼠标滚轮上下滚动。",foreground="#666",wraplength=560).pack(anchor="w",pady=(4,12))
        mode=ttk.LabelFrame(f,text="① 执行时间",padding=10); mode.pack(fill="x")
        ttk.Radiobutton(mode,text="立即执行（不创建定时）",variable=self.once_var,value=False).pack(anchor="w"); ttk.Radiobutton(mode,text="指定日期和时间",variable=self.once_var,value=True).pack(anchor="w",pady=(4,0))
        cal=ttk.LabelFrame(f,text="② 选择日期",padding=10); cal.pack(fill="x",pady=(12,0)); self.calendar=MonthCalendar(cal,self.selected_date,self.select_date); self.calendar.pack(fill="x")
        timeb=ttk.LabelFrame(f,text="③ 选择时间",padding=10); timeb.pack(fill="x",pady=(12,0)); ttk.Label(timeb,text="小时",width=6).grid(row=0,column=0,sticky="w"); self.hs=tk.Scale(timeb,from_=0,to=23,resolution=1,orient="horizontal",showvalue=False,variable=self.hour_var,length=360,command=lambda x:self.preview()); self.hs.grid(row=0,column=1,sticky="ew"); self.hl=ttk.Label(timeb,text="00",font=("Microsoft YaHei UI",14,"bold"),width=4); self.hl.grid(row=0,column=2); ttk.Label(timeb,text="分钟",width=6).grid(row=1,column=0,sticky="w"); self.ms=tk.Scale(timeb,from_=0,to=59,resolution=1,orient="horizontal",showvalue=False,variable=self.minute_var,length=360,command=lambda x:self.preview()); self.ms.grid(row=1,column=1,sticky="ew"); self.ml=ttk.Label(timeb,text="00",font=("Microsoft YaHei UI",14,"bold"),width=4); self.ml.grid(row=1,column=2); timeb.columnconfigure(1,weight=1)
        q=ttk.Frame(f); q.pack(fill="x",pady=10)
        for label,m in (("+5 分钟",5),("+10 分钟",10),("+30 分钟",30),("+1 小时",60)): ttk.Button(q,text=label,command=lambda mm=m:self.quick(mm)).pack(side="left",padx=3)
        ttk.Button(q,text="明天 09:00",command=self.tomorrow).pack(side="left",padx=3)
        self.prev=ttk.Label(f,font=("Microsoft YaHei UI",18,"bold")); self.prev.pack(anchor="w",pady=(8,12))
        ex=ttk.LabelFrame(f,text="④ 执行方式",padding=10); ex.pack(fill="x"); ttk.Checkbutton(ex,text="使用 Windows 任务计划（关闭主程序后仍可执行）",variable=self.system_var).pack(anchor="w"); ttk.Checkbutton(ex,text="发送完成后自动关机（30 秒倒计时）",variable=self.shutdown_var).pack(anchor="w",pady=(5,0)); ttk.Label(ex,text="电脑彻底关机后的自动开机取决于硬件/BIOS；扫码登录不由本程序代办。",foreground="#996600",wraplength=560).pack(anchor="w",pady=(6,0))
        b=ttk.Frame(f); b.pack(fill="x",pady=18); ttk.Button(b,text="取消",command=self.destroy).pack(side="right"); ttk.Button(b,text="保存",command=lambda:self.save(False)).pack(side="right",padx=8); ttk.Button(b,text="保存并启动",command=lambda:self.save(True)).pack(side="right")
        self.preview(); self.bind("<MouseWheel>",lambda e: sf.canvas.yview_scroll(int(-e.delta/120),"units"))
    def select_date(self,d): self.selected_date=d; self.preview()
    def setdt(self,dt): self.selected_date=dt.date(); self.hour_var.set(dt.hour); self.minute_var.set(dt.minute); self.calendar.year=dt.year; self.calendar.month=dt.month; self.calendar.selected=dt.date(); self.calendar.render(); self.preview()
    def quick(self,m): self.setdt(datetime.now()+timedelta(minutes=m))
    def tomorrow(self):
        d=datetime.now()+timedelta(days=1); self.setdt(d.replace(hour=9,minute=0,second=0,microsecond=0))
    def preview(self):
        h,m=int(self.hour_var.get()),int(self.minute_var.get()); self.hl.config(text=f"{h:02d}"); self.ml.config(text=f"{m:02d}"); self.prev.config(text=f"{self.selected_date:%Y-%m-%d} {h:02d}:{m:02d}")
    def save(self,start):
        if not self.once_var.get(): self.result={"schedule":{"mode":"now","datetime":""},"scheduler_mode":"app","auto_shutdown":False,"start":False}; self.destroy(); return
        dt=datetime(self.selected_date.year,self.selected_date.month,self.selected_date.day,int(self.hour_var.get()),int(self.minute_var.get()),0)
        if dt<=datetime.now(): messagebox.showwarning("时间无效","请选择未来的日期和时间。",parent=self); return
        self.result={"schedule":{"mode":"once","datetime":dt.strftime("%Y-%m-%d %H:%M:%S")},"scheduler_mode":"system" if self.system_var.get() else "app","auto_shutdown":bool(self.shutdown_var.get()),"start":start}; self.destroy()

class TargetDialog(tk.Toplevel):
    def __init__(self,parent,target=None,defaults=None):
        super().__init__(parent)
        self.title("编辑目标")
        self.geometry("720x800")
        self.minsize(620,640)
        self.transient(parent)
        self.grab_set()
        self.result=None
        self.target=json.loads(json.dumps(DEFAULT_TARGET,ensure_ascii=False))
        self.target.update(target or {})
        self.defaults=defaults or {}
        self.name_var=tk.StringVar(value=self.target.get("name",""))
        self.type_var=tk.StringVar(value={"contact":"联系人","group":"群聊"}.get(self.target.get("type","auto"),"自动"))
        self.order_var=tk.StringVar(value=self.target.get("send_order","text_then_images"))
        self.image_paths=list(self.target.get("images",[]))
        self.schedule_var=tk.StringVar(value=self._sched_text())
        self.enabled=tk.BooleanVar(value=bool(self.target.get("enabled",True)))
        self.shutdown=tk.BooleanVar(value=bool(self.target.get("auto_shutdown",False)))
        self._build_ui()
        self.after(30,self._focus_window)

    def _focus_window(self):
        try:
            self.update_idletasks()
            parent=self.master
            px,py=parent.winfo_rootx(),parent.winfo_rooty(); pw,ph=parent.winfo_width(),parent.winfo_height()
            ww,wh=self.winfo_width(),self.winfo_height()
            x=max(0,px+(pw-ww)//2); y=max(0,py+(ph-wh)//2)
            self.geometry(f"{ww}x{wh}+{x}+{y}")
            self.deiconify(); self.lift(); self.focus_force()
        except Exception:
            pass

    def _build_ui(self):
        sf=ScrollableFrame(self)
        sf.pack(fill="both",expand=True)
        f=sf.inner; f.configure(padding=18)
        ttk.Label(f,text="目标设置",font=("Microsoft YaHei UI",20,"bold")).pack(anchor="w")
        ttk.Label(f,text="每个联系人或群聊都可单独设置消息、图片和发送时间。",foreground="#666",wraplength=620).pack(anchor="w",pady=(4,14))

        info=ttk.LabelFrame(f,text="① 收件人",padding=10); info.pack(fill="x")
        r=ttk.Frame(info); r.pack(fill="x")
        ttk.Label(r,text="名称：").pack(side="left")
        ttk.Entry(r,textvariable=self.name_var,width=32).pack(side="left",padx=8)
        ttk.Label(r,text="类型：").pack(side="left")
        ttk.Combobox(r,textvariable=self.type_var,state="readonly",values=("自动","联系人","群聊"),width=10).pack(side="left")
        ttk.Label(info,text="例如：张三、李四工作群。类型不确定时可以保持“自动”。",foreground="#666").pack(anchor="w",pady=(8,0))

        msg=ttk.LabelFrame(f,text="② 消息内容",padding=10); msg.pack(fill="x",pady=(12,0))
        ttk.Label(msg,text="文字：").pack(anchor="w")
        self.text=tk.Text(msg,height=8,wrap="word")
        self.text.pack(fill="x",pady=6)
        self.text.insert("1.0",self.target.get("message","") or "")
        ir=ttk.Frame(msg); ir.pack(fill="x")
        ttk.Button(ir,text="选择图片（可多选）",command=self.choose_images).pack(side="left")
        ttk.Button(ir,text="清空图片",command=self.clear_images).pack(side="left",padx=8)
        self.image_label=ttk.Label(ir,text=self._img_text()); self.image_label.pack(side="left")
        orow=ttk.Frame(msg); orow.pack(fill="x",pady=(10,0))
        ttk.Label(orow,text="发送顺序：").pack(side="left")
        ttk.Radiobutton(orow,text="文字 → 图片",variable=self.order_var,value="text_then_images").pack(side="left",padx=8)
        ttk.Radiobutton(orow,text="图片 → 文字",variable=self.order_var,value="images_then_text").pack(side="left")

        sch=ttk.LabelFrame(f,text="③ 这个目标的发送时间",padding=10); sch.pack(fill="x",pady=(12,0))
        ttk.Label(sch,textvariable=self.schedule_var,font=("Microsoft YaHei UI",14,"bold")).pack(side="left")
        ttk.Button(sch,text="打开日历设置",command=self.open_schedule).pack(side="right")
        ttk.Label(sch,text="可设置到具体日期和分钟；每个目标可以不同。",foreground="#666").pack(anchor="w",pady=(8,0))

        safety=ttk.LabelFrame(f,text="④ 其它",padding=10); safety.pack(fill="x",pady=(12,0))
        ttk.Checkbutton(safety,text="启用这个目标",variable=self.enabled).pack(anchor="w")
        ttk.Checkbutton(safety,text="发送完成后自动关机（只建议最后一个目标使用）",variable=self.shutdown).pack(anchor="w",pady=(5,0))

        b=ttk.Frame(f); b.pack(fill="x",pady=18)
        ttk.Button(b,text="取消",command=self.destroy).pack(side="right")
        ttk.Button(b,text="保存",command=self.save).pack(side="right",padx=8)
        self.bind("<MouseWheel>",lambda e: sf.canvas.yview_scroll(int(-e.delta/120),"units"))

    def _img_text(self):
        if not self.image_paths: return "未选择图片"
        return Path(self.image_paths[0]).name if len(self.image_paths)==1 else f"已选择 {len(self.image_paths)} 张图片"
    def _sched_text(self):
        s=self.target.get("schedule",{})
        return s.get("datetime","立即发送") if s.get("mode")=="once" else "立即发送"
    def choose_images(self):
        p=filedialog.askopenfilenames(parent=self,title="选择要发送的图片（可多选）",filetypes=[("图片","*.png *.jpg *.jpeg *.bmp *.webp *.gif"),("所有文件","*.*")])
        if p: self.image_paths=list(p); self.image_label.config(text=self._img_text())
    def clear_images(self): self.image_paths=[]; self.image_label.config(text="未选择图片")
    def open_schedule(self):
        dlg=ScheduleDialog(self,self.target); self.wait_window(dlg)
        if dlg.result:
            self.target["schedule"]=dlg.result["schedule"]
            self.target["scheduler_mode"]=dlg.result["scheduler_mode"]
            self.target["auto_shutdown"]=bool(dlg.result["auto_shutdown"])
            self.schedule_var.set(self._sched_text())
    def save(self):
        name=self.name_var.get().strip(); msg=self.text.get("1.0","end").strip()
        if not name:
            messagebox.showwarning("提示","请输入联系人或群聊名称。",parent=self); return
        if not msg and not self.image_paths:
            messagebox.showwarning("提示","文字和图片至少需要一种。",parent=self); return
        typ={"联系人":"contact","群聊":"group"}.get(self.type_var.get(),"auto")
        out=json.loads(json.dumps(DEFAULT_TARGET,ensure_ascii=False)); out.update(self.target)
        out.update({"name":name,"type":typ,"message":msg,"images":list(self.image_paths),"send_order":self.order_var.get(),"enabled":bool(self.enabled.get()),"auto_shutdown":bool(self.shutdown.get() and self.target.get("scheduler_mode")=="system")})
        self.result=out; self.destroy()

class LiveRegionOverlay(tk.Toplevel):
    """直接叠加到当前桌面的预览层；右上角按钮或 ESC 均可关闭。"""
    def __init__(self,parent,rects,origin=(0,0),screen_size=(1920,1080),virtual_origin=(0,0),title="微信区域预览",on_close=None):
        super().__init__(parent)
        self._on_close_cb=on_close; self._closed=False
        self.title(title); self.overrideredirect(True); self.attributes("-topmost",True)
        vx,vy=virtual_origin; sw,sh=screen_size
        self.geometry(f"{sw}x{sh}{vx:+d}{vy:+d}")
        transparent="#010101"
        try: self.attributes("-transparentcolor",transparent)
        except Exception: pass
        cv=tk.Canvas(self,width=sw,height=sh,bg=transparent,highlightthickness=0)
        cv.pack(fill="both",expand=True)
        self.canvas=cv; self.screen_size=(sw,sh)
        ox,oy=origin
        cv.create_text(18,18,text=title,anchor="nw",fill="#00ff66",font=("Microsoft YaHei UI",14,"bold"))
        for idx,(label,(x,y,w,h)) in enumerate(rects,1):
            lx,ly=x-vx,y-vy
            cv.create_rectangle(lx,ly,lx+w,ly+h,outline="#00e676",width=4)
            label_text=f"{idx}. {label}"
            tw=max(110,18*len(label_text)+18)
            cv.create_rectangle(lx,ly,lx+tw,ly+28,fill="#101010",outline="#00e676")
            cv.create_text(lx+8,ly+5,text=label_text,fill="#00e676",anchor="nw",font=("Microsoft YaHei UI",10,"bold"))
        bx=max(20,sw-180); by=16
        cv.create_rectangle(bx,by,bx+155,by+38,fill="#111111",outline="#00e676",width=2)
        cv.create_text(bx+12,by+8,text="关闭预览  (ESC)",anchor="nw",fill="white",font=("Microsoft YaHei UI",11,"bold"))
        cv.bind("<Button-1>", self._click_close)
        self.bind("<Escape>",lambda e:self.close())
        self.bind("<Destroy>",lambda e:self._after_destroy(e),add="+")
        self.after(50,self._focus)
    def _focus(self):
        try:self.deiconify(); self.lift(); self.focus_force()
        except Exception:pass
    def _click_close(self,event):
        sw,sh=self.screen_size
        if event.x>=sw-180 and event.x<=sw-10 and event.y<=70:
            self.close()
    def close(self):
        if self._closed:return
        self._closed=True
        try:self.grab_release()
        except Exception:pass
        try:self.destroy()
        except Exception:pass
    def _after_destroy(self,event):
        if event.widget is self and self._on_close_cb:
            try:self._on_close_cb()
            except Exception:pass

class RegionOverlay(tk.Toplevel):
    def __init__(self,parent,image,rects,origin=(0,0),title="当前区域"): 
        super().__init__(parent); self.title(title); self.geometry(f"{image.width+20}x{image.height+80}"); self.transient(parent); self.grab_set(); self.photo=None
        from PIL import ImageTk
        frame=ttk.Frame(self,padding=8); frame.pack(fill="both",expand=True); ttk.Label(frame,text=title,font=("Microsoft YaHei UI",14,"bold")).pack(anchor="w"); cv=tk.Canvas(frame,width=image.width,height=image.height,highlightthickness=0); cv.pack(fill="both",expand=True)
        self.photo=ImageTk.PhotoImage(image,master=self); cv.create_image(0,0,image=self.photo,anchor="nw")
        ox,oy=origin
        # rects are absolute screen coordinates; convert to overlay-local coordinates.
        for idx,(label,(x,y,w,h)) in enumerate(rects,1):
            lx,ly=x-ox,y-oy; cv.create_rectangle(lx,ly,lx+w,ly+h,outline="#00d26a",width=4); cv.create_rectangle(lx,ly,lx+110,ly+26,fill="#111",outline=""); cv.create_text(lx+8,ly+4,text=f"{idx}. {label}",fill="#00d26a",anchor="nw",font=("Microsoft YaHei UI",10,"bold"))
        ttk.Button(frame,text="关闭 / ESC",command=self.destroy).pack(pady=8); self.bind("<Escape>",lambda e:self.destroy())

class OCRDialog(tk.Toplevel):
    def __init__(self,parent,rows):
        super().__init__(parent); self.title("OCR 识别结果"); self.geometry("860x560"); self.transient(parent); self.grab_set(); f=ttk.Frame(self,padding=12); f.pack(fill="both",expand=True); ttk.Label(f,text="OCR 结果 + 分类",font=("Microsoft YaHei UI",14,"bold")).pack(anchor="w"); cols=("text","section","score","box"); tree=ttk.Treeview(f,columns=cols,show="headings");
        for c,t,w in (("text","文字",300),("section","分类",160),("score","置信度",130),("box","位置",230)): tree.heading(c,text=t); tree.column(c,width=w)
        tree.pack(side="left",fill="both",expand=True); sb=ttk.Scrollbar(f,orient="vertical",command=tree.yview); sb.pack(side="right",fill="y"); tree.configure(yscrollcommand=sb.set)
        for item in rows: tree.insert("","end",values=(item.text,item.section,f"{item.score:.3f}",f"{item.box[0]},{item.box[1]} - {item.box[2]},{item.box[3]}"))
        ttk.Button(f,text="关闭",command=self.destroy).pack(pady=8)

class App:
    def __init__(self,root):
        self.root=root; self.root.title(APP_TITLE); self.root.geometry("1280x900"); self.root.minsize(900,680); self.settings=load_settings(); self.tasks,_=migrate_tasks(load_tasks_file());
        if not self.tasks: self.tasks=[new_task()]; save_tasks_file(self.tasks)
        else: save_tasks_file(self.tasks)
        self.current_task_id=self.settings.get("last_task_id") or self.tasks[0]["id"]; self.current_task=next((t for t in self.tasks if t.get("id")==self.current_task_id),self.tasks[0]); self.current_task_id=self.current_task["id"]
        self.target_name_var=tk.StringVar(); self.target_type_var=tk.StringVar(value="自动"); self.task_name_var=tk.StringVar(); self.search_region_var=tk.StringVar(); self.verify_region_var=tk.StringVar(); self.status_var=tk.StringVar(value="准备就绪"); self.verify_var=tk.BooleanVar(value=True); self.continue_var=tk.BooleanVar(value=False); self.schedule_status=tk.StringVar(value="未启动定时")
        self.style=ttk.Style(self.root); self.style.theme_use("clam"); self._last_suggestions={}; self._live_overlay=None; self.scheduler=MultiTargetScheduler(self.execute_scheduled_job,self.set_status); self.automation=None; self.apply_theme(self.settings.get("theme","浅色")); self.set_icon(); self.build_ui(); self.load_current_task(); self.root.protocol("WM_DELETE_WINDOW",self.on_close)
    def set_status(self, text):
        """线程安全地更新底部状态栏，同时写入日志。"""
        message = str(text)
        try:
            logging.info(message)
        except Exception:
            pass
        try:
            if threading.current_thread() is threading.main_thread():
                self.status_var.set(message)
            else:
                self.root.after(0, lambda m=message: self.status_var.set(m))
        except Exception:
            try:
                self.status_var.set(message)
            except Exception:
                pass
    def set_icon(self):
        try:
            from PIL import ImageTk
            img=load_avatar_image()
            if img is None:
                return
            img.thumbnail((64,64))
            self.icon_photo=ImageTk.PhotoImage(img,master=self.root)
            self.root.iconphoto(True,self.icon_photo)
        except Exception:
            logging.exception("加载程序图标失败")
    def about(self): AboutDialog(self.root)
    def build_ui(self):
        out=ttk.Frame(self.root,padding=16); out.pack(fill="both",expand=True); hdr=ttk.Frame(out); hdr.pack(fill="x")
        brand=ttk.Frame(hdr); brand.pack(side="left",fill="x",expand=True); tr=ttk.Frame(brand); tr.pack(anchor="w"); ttk.Label(tr,text=APP_TITLE,font=("Microsoft YaHei UI",24,"bold")).pack(side="left"); ttk.Label(tr,text=f"  {APP_VERSION}",foreground="#6b7280",font=("Microsoft YaHei UI",10,"bold")).pack(side="left",pady=(10,0)); ttk.Label(brand,text=f"Edgar Jingxiu · 多目标独立消息 · 独立时间 · OCR 核验 · Windows 系统计划",foreground="#6b7280").pack(anchor="w",pady=(4,0))
        right=ttk.Frame(hdr); right.pack(side="right");
        try:
            from PIL import ImageTk
            img=load_avatar_image()
            if img is None:
                raise RuntimeError("头像资源不存在")
            img.thumbnail((54,54))
            self.avatar=ImageTk.PhotoImage(img,master=right)
            ttk.Button(right,image=self.avatar,command=self.about).pack(side="right",padx=4)
        except Exception:
            ttk.Button(right,text="Edgar",command=self.about).pack(side="right")
        nb=ttk.Notebook(out); nb.pack(fill="both",expand=True,pady=(12,0)); self.main_tab=ScrollableFrame(nb); self.calib_tab=ScrollableFrame(nb); self.adv_tab=ScrollableFrame(nb); self.exp_tab=ScrollableFrame(nb); nb.add(self.main_tab,text="任务编辑"); nb.add(self.calib_tab,text="校准与核验"); nb.add(self.adv_tab,text="高级设置"); nb.add(self.exp_tab,text="实验功能"); self.build_task_tab(); self.build_calib_tab(); self.build_adv_tab(); self.build_exp_tab()
        st=ttk.Frame(out); st.pack(fill="x",pady=(10,0)); ttk.Label(st,text="状态：",font=("Microsoft YaHei UI",10,"bold")).pack(side="left"); ttk.Label(st,textvariable=self.status_var,foreground="#0066aa").pack(side="left",fill="x",expand=True); ttk.Label(st,text=f"Edgar Jingxiu · {APP_EMAIL}",foreground="#9ca3af",font=("Microsoft YaHei UI",8)).pack(side="right")
    def build_task_tab(self):
        f=self.main_tab.inner; top=ttk.LabelFrame(f,text="① 当前任务",padding=10); top.pack(fill="x"); ttk.Label(top,text="任务名称：").pack(side="left"); ttk.Entry(top,textvariable=self.task_name_var,width=30).pack(side="left",padx=8); ttk.Button(top,text="新建任务",command=self.new_task).pack(side="right"); ttk.Button(top,text="保存任务",command=self.save_current_task).pack(side="right",padx=8); ttk.Button(top,text="删除当前任务",command=self.delete_task).pack(side="right")
        box=ttk.LabelFrame(f,text="② 目标列表（每个联系人 / 群聊单独设置消息与时间）",padding=10); box.pack(fill="x",pady=(10,0)); r=ttk.Frame(box); r.pack(fill="x"); ttk.Label(r,text="快速添加名称：").pack(side="left"); ttk.Entry(r,textvariable=self.target_name_var,width=28).pack(side="left",padx=8); ttk.Label(r,text="类型：").pack(side="left"); ttk.Combobox(r,textvariable=self.target_type_var,state="readonly",values=("自动","联系人","群聊"),width=10).pack(side="left",padx=6); ttk.Button(r,text="添加并编辑",command=self.quick_add).pack(side="left",padx=8); ttk.Button(r,text="编辑选中",command=self.edit_target).pack(side="left"); ttk.Button(r,text="删除选中",command=self.remove_target).pack(side="left",padx=8)
        cols=("type","name","message","time","mode","enabled"); self.targets_tree=ttk.Treeview(box,columns=cols,show="headings",height=8); widths=(80,220,360,170,100,70); titles=("类型","目标","消息摘要","时间","执行方式","启用");
        for c,t,w in zip(cols,titles,widths): self.targets_tree.heading(c,text=t); self.targets_tree.column(c,width=w)
        self.targets_tree.pack(fill="x",pady=(8,0)); self.targets_tree.bind("<Double-1>",lambda e:self.edit_target()); ttk.Label(box,text="操作：输入目标名称 → 添加并编辑 → 设置消息/时间 → 保存。双击列表可再次编辑。",foreground="#44546a",wraplength=900).pack(anchor="w",pady=(6,0))
        a=ttk.Frame(f); a.pack(fill="x",pady=(10,0)); ttk.Button(a,text="立即发送全部已启用目标",command=self.send_all_now).pack(side="left",ipadx=10,ipady=6); ttk.Button(a,text="启动当前任务的全部定时",command=self.start_all_schedules).pack(side="left",padx=8,ipadx=10,ipady=6); ttk.Button(a,text="取消当前任务全部定时",command=self.cancel_all_schedules).pack(side="left",ipadx=10,ipady=6); ttk.Label(a,textvariable=self.schedule_status,foreground="#666").pack(side="left",padx=14)
        tb=ttk.LabelFrame(f,text="③ 已保存任务",padding=8); tb.pack(fill="x",pady=(12,0)); cols2=("name","targets","scheduled","enabled"); self.task_tree=ttk.Treeview(tb,columns=cols2,show="headings",height=5); 
        for c,t,w in (("name","任务",260),("targets","目标数",100),("scheduled","定时目标",120),("enabled","启用",70)): self.task_tree.heading(c,text=t); self.task_tree.column(c,width=w)
        self.task_tree.pack(fill="x"); self.task_tree.bind("<<TreeviewSelect>>",self.select_task); self.refresh_task_tree()
    def build_calib_tab(self):
        f=self.calib_tab.inner; inf=ttk.LabelFrame(f,text="区域只保存为相对微信客户区的位置，拖动微信窗口后会跟着走。",padding=12); inf.pack(fill="x"); ttk.Label(inf,textvariable=self.search_region_var).pack(anchor="w"); ttk.Label(inf,textvariable=self.verify_region_var).pack(anchor="w",pady=(4,0)); ttk.Button(inf,text="检查 / 启动微信（不发送）",command=self.check_wechat_only).pack(anchor="w",pady=(10,0)); ttk.Button(inf,text="清除屏幕上正在显示的框",command=self.clear_live_overlay).pack(anchor="w",pady=(6,0)); ttk.Label(inf,text="用途：测试微信状态，不发送消息。最小化会先恢复；未打开时先尝试 Win+S，并等待系统搜索动画结束后才输入“微信”。如果进入扫码登录页，程序会停止，不会继续点击或发送。",foreground="#44546a",wraplength=900).pack(anchor="w",pady=(6,0))
        g=ttk.LabelFrame(f,text="① 搜索结果 OCR 区域",padding=12); g.pack(fill="x",pady=(12,0)); ttk.Button(g,text="重新框选搜索结果",command=self.select_search).pack(side="left"); ttk.Button(g,text="屏幕显示搜索框",command=lambda:self.show_live_regions(("search",))).pack(side="left",padx=8); ttk.Button(g,text="截图查看搜索框",command=lambda:self.show_regions(("search",))).pack(side="left"); ttk.Button(g,text="测试 OCR",command=self.test_ocr).pack(side="left"); ttk.Label(g,text="怎么框：只框左侧搜索结果列表，不要框顶部搜索输入框；上下留一点余量，右侧可多留一些空间。",foreground="#44546a",wraplength=900).pack(anchor="w",pady=(8,0))
        g2=ttk.LabelFrame(f,text="② 聊天标题核验",padding=12); g2.pack(fill="x",pady=(12,0)); ttk.Button(g2,text="框选聊天标题（1 个即可）",command=self.select_verify).pack(side="left"); ttk.Button(g2,text="屏幕显示标题框",command=lambda:self.show_live_regions(("verify",))).pack(side="left",padx=8); ttk.Button(g2,text="截图查看标题框",command=lambda:self.show_regions(("verify",))).pack(side="left"); ttk.Label(g2,text="怎么框：进入正确聊天后，只框顶部聊天名称，四周留一点空白；不要碰到左侧“+”或右侧功能按钮，底边不要进入聊天内容区。与搜索框重叠没关系。",foreground="#44546a",wraplength=900).pack(anchor="w",pady=(8,0))
        g3=ttk.LabelFrame(f,text="③ 微信布局助手",padding=12); g3.pack(fill="x",pady=(12,0)); ttk.Button(g3,text="扫描窗口并显示建议框",command=self.layout_helper).pack(side="left"); ttk.Button(g3,text="截图查看建议框",command=self.layout_helper_image).pack(side="left",padx=8); ttk.Button(g3,text="应用建议框到当前任务",command=self.apply_suggestions).pack(side="left",padx=8); ttk.Label(g3,text="怎么用：自动给出“搜索结果”和“聊天标题”两个参考框；位置只作参考，合适后再应用。",foreground="#44546a",wraplength=900).pack(anchor="w",pady=(8,0)); ttk.Button(g3,text="显示全部已保存框",command=lambda:self.show_live_regions(("all",))).pack(anchor="w",pady=(10,0))
        ttk.Button(f,text="测试点击（只进入目标，不发送）",command=self.test_click).pack(anchor="w",pady=18,ipadx=12,ipady=5)
    def build_adv_tab(self):
        f=self.adv_tab.inner; s=ttk.LabelFrame(f,text="目标安全",padding=12); s.pack(fill="x"); ttk.Checkbutton(s,text="发送前进行聊天标题核验（推荐）",variable=self.verify_var).pack(anchor="w"); ttk.Checkbutton(s,text="某目标失败时继续后续目标（关闭则立即停止）",variable=self.continue_var).pack(anchor="w",pady=(6,0)); ttk.Label(s,text="默认只需要 1 个标题核验框。",foreground="#666").pack(anchor="w",pady=(8,0))
        p=ttk.LabelFrame(f,text="识别与发送速度",padding=12); p.pack(fill="x",pady=(12,0)); self.retry=tk.IntVar(value=int(self.settings.get("ocr_retry_count",5))); self.wait=tk.DoubleVar(value=float(self.settings.get("send_wait",0.9))); ttk.Label(p,text="OCR 重试次数（1~10）").grid(row=0,column=0,sticky="w",pady=6); tk.Spinbox(p,from_=1,to=10,textvariable=self.retry,width=7).grid(row=0,column=1,sticky="w"); ttk.Label(p,text="发送后等待秒数（0.2~3）").grid(row=1,column=0,sticky="w",pady=6); tk.Spinbox(p,from_=0.2,to=3.0,increment=0.1,textvariable=self.wait,width=7).grid(row=1,column=1,sticky="w"); ttk.Button(p,text="保存高级设置",command=self.save_adv).grid(row=2,column=0,columnspan=2,pady=8)
        t=ttk.LabelFrame(f,text="主题与外观",padding=12); t.pack(fill="x",pady=(12,0)); self.theme=tk.StringVar(value=self.settings.get("theme","浅色")); ttk.Label(t,text="主题：").pack(side="left"); ttk.Combobox(t,textvariable=self.theme,values=tuple(THEMES.keys()),state="readonly",width=10).pack(side="left",padx=8); ttk.Button(t,text="应用主题",command=self.apply_theme_ui).pack(side="left"); ttk.Button(t,text="选择顶部装饰图片",command=self.choose_banner).pack(side="left",padx=8); ttk.Button(t,text="清除",command=self.clear_banner).pack(side="left")
        r=ttk.LabelFrame(f,text="任务文件 / 远程端预留",padding=12); r.pack(fill="x",pady=(12,0)); ttk.Button(r,text="导出当前任务 JSON",command=self.export_task).pack(side="left"); ttk.Button(r,text="导入任务 JSON",command=self.import_task).pack(side="left",padx=8); ttk.Label(r,text="V13 的任务结构已经按‘目标独立消息/时间’设计，方便以后手机端下发。",foreground="#666").pack(anchor="w",pady=(8,0))
        d=ttk.LabelFrame(f,text="诊断",padding=12); d.pack(fill="x",pady=(12,0)); ttk.Button(d,text="打开日志文件夹",command=lambda:os.startfile(str(LOG_FILE.parent))).pack(side="left"); ttk.Button(d,text="屏幕显示搜索区域",command=lambda:self.show_live_regions(("search",))).pack(side="left",padx=8); ttk.Button(d,text="清除屏幕框",command=self.clear_live_overlay).pack(side="left",padx=8); ttk.Button(d,text="截图查看搜索区域",command=lambda:self.show_regions(("search",))).pack(side="left")
    def build_exp_tab(self):
        f=self.exp_tab.inner; b=ttk.LabelFrame(f,text="实验性：AI 自动聊天",padding=16); b.pack(fill="x"); ttk.Label(b,text="暂不接入核心发送链路。",font=("Microsoft YaHei UI",15,"bold")).pack(anchor="w"); ttk.Label(b,text="后续可以单独研究：聊天内容捕获 → 上下文整理 → AI 生成回复 → 预览 → 自动发送。",wraplength=900).pack(anchor="w",pady=12); ttk.Button(b,text="查看说明",command=lambda:messagebox.showinfo("实验功能","AI 自动聊天仍属于实验项目，不会影响 核心发送功能。",parent=self.root)).pack(anchor="w",pady=12)
    def load_current_task(self):
        self.current_task=next((t for t in self.tasks if t.get("id")==self.current_task_id),self.tasks[0]); self.current_task_id=self.current_task["id"]; self.task_name_var.set(self.current_task.get("name","新任务")); self.verify_var.set(bool(self.current_task.get("verify_target",True))); self.continue_var.set(bool(self.current_task.get("continue_on_error",False))); self.refresh_targets(); self.refresh_regions(); self.settings["last_task_id"]=self.current_task_id; save_settings(self.settings); self.refresh_task_tree()
    def refresh_targets(self):
        if not self.targets_tree:return
        for i in self.targets_tree.get_children():self.targets_tree.delete(i)
        for i,t in enumerate(self.current_task.get("targets",[])):
            msg=str(t.get("message","") or "").replace("\n"," "); summary=(msg[:42]+"…") if len(msg)>43 else (msg or f"{len(t.get('images',[]))} 张图片"); s=t.get("schedule",{}); tm=s.get("datetime","立即") if s.get("mode")=="once" else "立即"; mode="系统计划" if t.get("scheduler_mode")=="system" else ("应用内" if s.get("mode")=="once" else "立即"); self.targets_tree.insert("","end",iid=str(i),values=({"contact":"联系人","group":"群聊"}.get(t.get("type"),"自动"),t.get("name",""),summary,tm,mode,"是" if t.get("enabled",True) else "否"))
    def refresh_task_tree(self,select_id=None):
        if not getattr(self,"task_tree",None):return
        for i in self.task_tree.get_children():self.task_tree.delete(i)
        for t in self.tasks:
            scheduled=sum(1 for x in t.get("targets",[]) if x.get("schedule",{}).get("mode")=="once"); self.task_tree.insert("","end",iid=t["id"],values=(t.get("name",""),len(t.get("targets",[])),scheduled,"是" if t.get("enabled",True) else "否"))
        sid=select_id or self.current_task_id
        if self.task_tree.exists(sid): self.task_tree.selection_set(sid)
    def collect_ui(self):
        self.current_task["name"]=self.task_name_var.get().strip() or "未命名任务"; self.current_task["verify_target"]=bool(self.verify_var.get()); self.current_task["continue_on_error"]=bool(self.continue_var.get()); vals=[]
        for iid in self.targets_tree.get_children():
            idx=int(iid); vals.append(self.current_task["targets"][idx])
        self.current_task["targets"]=vals; return self.current_task
    def save_current_task(self,silent=False):
        try:
            task=self.collect_ui()
            if not task.get("targets"): raise ValueError("请至少添加一个目标。")
            if not task.get("search_region"): raise ValueError("请先框选搜索结果 OCR 区域。")
            for t in task["targets"]:
                if not t.get("message") and not t.get("images"): raise ValueError(f"目标‘{t.get('name','')}’没有配置文字或图片。")
                for p in t.get("images",[]):
                    if not os.path.isfile(p): raise ValueError(f"图片不存在：{p}")
            for i,t in enumerate(task["targets"]):
                if t.get("scheduler_mode")=="system" and not t.get("schedule",{}).get("datetime"): t["scheduler_mode"]="app"
            self.tasks=[task if x.get("id")==task.get("id") else x for x in self.tasks]; save_tasks_file(self.tasks); self.refresh_targets(); self.refresh_task_tree(task["id"]); self.set_status("任务已保存。"); return True
        except Exception as exc:
            if not silent: messagebox.showerror("保存失败",str(exc),parent=self.root)
            return False
    def new_task(self):
        if self.current_task and not self.save_current_task(silent=True): return
        t=new_task(); self.tasks.append(t); self.current_task_id=t["id"]; self.current_task=t; self.load_current_task(); self.set_status("已创建新任务。")
    def delete_task(self):
        if len(self.tasks)<=1: messagebox.showwarning("不能删除","至少保留一个任务。",parent=self.root); return
        self.cancel_all_schedules(silent=True)
        self.tasks=[t for t in self.tasks if t.get("id")!=self.current_task_id]; self.current_task_id=self.tasks[0]["id"]; save_tasks_file(self.tasks); self.load_current_task(); self.set_status("任务已删除。")
    def select_task(self,_=None):
        sel=self.task_tree.selection();
        if not sel:return
        tid=sel[0]
        if tid==self.current_task_id:return
        if not self.save_current_task(silent=True):return
        self.current_task_id=tid; self.load_current_task()
    def quick_add(self):
        name=self.target_name_var.get().strip()
        if not name:
            messagebox.showwarning("提示","先在左侧输入联系人或群聊名称，再点击‘添加并编辑’。",parent=self.root)
            return
        td={"name":name,"type":{"联系人":"contact","群聊":"group"}.get(self.target_type_var.get(),"auto")}
        dlg=TargetDialog(self.root,td)
        self.root.wait_window(dlg)
        if dlg.result:
            self.current_task.setdefault("targets",[]).append(dlg.result)
            self.refresh_targets()
            self._select_target_row(len(self.current_task["targets"])-1)
            save_tasks_file(self.tasks)
            self.target_name_var.set("")
            self.set_status(f"已添加目标：{dlg.result.get('name','')}")
    def edit_target(self):
        sel=self.targets_tree.selection()
        if not sel:
            messagebox.showwarning("提示","请先在目标列表中选中一行。",parent=self.root)
            return
        try:
            idx=int(sel[0])
        except Exception:
            messagebox.showerror("编辑失败","无法识别当前选中的目标。",parent=self.root)
            return
        if idx<0 or idx>=len(self.current_task.get("targets",[])):
            messagebox.showerror("编辑失败","选中的目标已经不存在，请刷新任务后再试。",parent=self.root)
            return
        dlg=TargetDialog(self.root,self.current_task["targets"][idx])
        self.root.wait_window(dlg)
        if dlg.result:
            self.current_task["targets"][idx]=dlg.result
            self.refresh_targets()
            self._select_target_row(idx)
            save_tasks_file(self.tasks)
            self.set_status(f"已更新目标：{dlg.result.get('name','')}")
    def _select_target_row(self, idx):
        iid=str(idx)
        if self.targets_tree.exists(iid):
            self.targets_tree.selection_set(iid)
            self.targets_tree.focus(iid)
            self.targets_tree.see(iid)
    def remove_target(self):
        sel=self.targets_tree.selection();
        if not sel:return
        ids=sorted((int(x) for x in sel),reverse=True)
        for idx in ids: self.cancel_target_schedule(self.current_task["targets"][idx],silent=True); self.current_task["targets"].pop(idx)
        self.refresh_targets(); self.save_current_task(silent=True); self.set_status("目标已删除。")
    def refresh_regions(self):
        r=self.current_task.get("search_region"); self.search_region_var.set("搜索区域："+(f"x={r['x']} y={r['y']} w={r['width']} h={r['height']}（相对微信客户区）" if r else "未设置")); self.verify_region_var.set(f"聊天标题核验区：{len(self.current_task.get('verify_regions',[]))} 个（默认 1 个）")
    def select_search(self):
        targets=self.current_task.get("targets",[])
        if not targets:
            messagebox.showwarning("还不能框选搜索结果","请先回到‘任务编辑’，添加至少一个联系人或群聊，并保存它的名称。然后再回来点这个按钮。",parent=self.root)
            return
        target=str(targets[0].get("name","")).strip()
        if not target:
            messagebox.showwarning("暂时不能框选","第一个目标还没有填写名称，请先编辑目标。",parent=self.root)
            return
        self.set_status("正在启动微信并搜索第一个目标，随后进入框选。")
        def work():
            try:
                a=self.ensure(); hwnd=a.search(target); client=a.client_rect(hwnd); self.root.after(0,lambda:self._open_search_selector(client))
            except Exception as exc: logging.exception("搜索区域准备失败"); self.root.after(0,lambda:messagebox.showerror("框选准备失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()
    def _open_search_selector(self,client):
        selector=AreaSelector(self.root,client); result=selector.select();
        if result:self.current_task["search_region"]=result.to_dict(); self.refresh_regions(); self.save_current_task(silent=True); self.set_status("搜索结果 OCR 区域已保存。")
    def select_verify(self):
        targets=self.current_task.get("targets",[])
        if not targets:
            messagebox.showwarning("还不能框选聊天标题","请先在‘任务编辑’里添加一个联系人或群聊，然后才能自动进入聊天页面进行标题核验。",parent=self.root)
            return
        target=str(targets[0].get("name","")).strip()
        if not target:
            messagebox.showwarning("暂时不能框选","第一个目标还没有填写名称，请先编辑目标。",parent=self.root)
            return
        sr=self.current_task.get("search_region")
        if not sr:
            messagebox.showwarning("暂时不能框选","请先完成‘搜索结果区域’框选。",parent=self.root)
            return
        def work():
            try:
                a=self.ensure(); hwnd=a.search(target); a.click_target(hwnd,RegionInfo.from_dict(sr),target,self.current_task["targets"][0].get("type","auto")); client=a.client_rect(hwnd); self.root.after(0,lambda:self._open_verify_selector(client))
            except Exception as exc: logging.exception("核验框准备失败"); self.root.after(0,lambda:messagebox.showerror("核验框准备失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()
    def _open_verify_selector(self,client):
        selector=MultiRegionSelector(self.root,client,"框选聊天标题（目标核验）","建议只框住顶部显示‘张三’或‘李四工作群 (8)’的标题区域；框可以稍微向左、向下扩大一点。Enter 完成，ESC 取消。",max_regions=1); result=selector.select();
        if result:self.current_task["verify_regions"]=[x.to_dict() for x in result]; self.refresh_regions(); self.save_current_task(silent=True); self.set_status("聊天标题核验框已保存。")
    def check_wechat_only(self):
        self.set_status("正在检查 / 启动微信，不会发送消息。")
        def work():
            try:
                a=self.ensure(); hwnd=a.ensure_logged_in(); self.set_status("微信已进入可操作状态；没有发送消息。")
                self.root.after(0,lambda:messagebox.showinfo("微信检查完成","已找到并激活可操作的微信窗口。\n\n本次检查没有发送任何消息。",parent=self.root))
            except Exception as exc:
                logging.exception("微信检查失败")
                self.root.after(0,lambda:messagebox.showerror("微信检查失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()

    def ensure(self):
        if self.automation is None:self.automation=WeChatAutomation(status_callback=self.set_status,ocr_retry_count=int(self.settings.get("ocr_retry_count",5)),send_wait=float(self.settings.get("send_wait",0.9)))
        return self.automation
    def _collect_region_view(self, labels):
        snap=json.loads(json.dumps(self.current_task,ensure_ascii=False))
        a=self.ensure(); hwnd=a.ensure_logged_in(); left,top,w,h=a.client_rect(hwnd); rects=[]
        if snap.get("search_region") and ("search" in labels or "all" in labels):
            rects.append(("搜索结果",a.screen_rect_from_region(hwnd,RegionInfo.from_dict(snap["search_region"]))))
        if "verify" in labels or "all" in labels:
            for v in snap.get("verify_regions",[]):
                rects.append(("聊天标题",a.screen_rect_from_region(hwnd,RegionInfo.from_dict(v))))
        if not rects: raise ValueError("当前任务没有保存可显示的区域。")
        return a, hwnd, (left,top,w,h), rects

    def show_live_regions(self,labels):
        def work():
            try:
                a,hwnd,client,rects=self._collect_region_view(labels)
                vx,vy,vw,vh=self._virtual_screen()
                def open_overlay():
                    self.clear_live_overlay()
                    self._live_overlay=LiveRegionOverlay(self.root,rects,client[:2],(vw,vh),(vx,vy),"微信区域（直接屏幕显示）",on_close=self._live_overlay_closed)
                    self.set_status("已在屏幕上显示区域。可点击右上角‘关闭预览’或按 ESC 清除。")
                self.root.after(0,open_overlay)
            except Exception as exc:
                logging.exception("直接显示区域失败")
                self.root.after(0,lambda:messagebox.showerror("显示区域失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()

    def _live_overlay_closed(self):
        self._live_overlay=None

    def clear_live_overlay(self):
        overlay=self._live_overlay
        if overlay is not None:
            try: overlay.close()
            except Exception:
                try: overlay.destroy()
                except Exception: pass
        self._live_overlay=None

    @staticmethod
    def _virtual_screen():
        try:
            user32=ctypes.windll.user32
            return (int(user32.GetSystemMetrics(76)),int(user32.GetSystemMetrics(77)),int(user32.GetSystemMetrics(78)),int(user32.GetSystemMetrics(79)))
        except Exception:
            return (0,0,1920,1080)

    def show_regions(self,labels):
        def work():
            try:
                a,hwnd,client,rects=self._collect_region_view(labels)
                left,top,w,h=client
                from PIL import ImageGrab
                img=ImageGrab.grab(bbox=(left,top,left+w,top+h))
                self.root.after(0,lambda:RegionOverlay(self.root,img,rects,(left,top),"微信区域截图查看"))
            except Exception as exc:
                logging.exception("截图查看区域失败")
                self.root.after(0,lambda:messagebox.showerror("截图查看失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()

    def _get_layout_suggestions(self):
        a=self.ensure(); hwnd=a.ensure_logged_in(); client=a.client_rect(hwnd); sug=suggest_regions(client); self._last_suggestions=sug; return a,hwnd,client,sug

    def layout_helper(self):
        def work():
            try:
                a,hwnd,client,sug=self._get_layout_suggestions(); left,top,w,h=client
                rects=[("建议：搜索结果",a.screen_rect_from_region(hwnd,sug["search"])),("建议：聊天标题",a.screen_rect_from_region(hwnd,sug["header"]))]
                vx,vy,vw,vh=self._virtual_screen()
                def open_layout_overlay():
                    self.clear_live_overlay()
                    self._live_overlay=LiveRegionOverlay(self.root,rects,(left,top),(vw,vh),(vx,vy),"微信布局建议（直接屏幕显示）",on_close=self._live_overlay_closed)
                    self.set_status("布局建议已显示。需要清除时可点击‘清除屏幕框’或按 ESC。")
                self.root.after(0,open_layout_overlay)
            except Exception as exc:
                logging.exception("布局助手失败")
                self.root.after(0,lambda:messagebox.showerror("布局助手失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()

    def layout_helper_image(self):
        def work():
            try:
                a,hwnd,client,sug=self._get_layout_suggestions(); left,top,w,h=client
                from PIL import ImageGrab
                img=ImageGrab.grab(bbox=(left,top,left+w,top+h)); rects=[("建议：搜索结果",a.screen_rect_from_region(hwnd,sug["search"])),("建议：聊天标题",a.screen_rect_from_region(hwnd,sug["header"]))]
                self.root.after(0,lambda:RegionOverlay(self.root,img,rects,(left,top),"微信布局建议（截图查看）"))
            except Exception as exc:
                logging.exception("布局助手截图失败")
                self.root.after(0,lambda:messagebox.showerror("截图查看失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()

    def apply_suggestions(self):
        def work():
            try:
                a=self.ensure(); sug=suggest_regions(a.client_rect(a.ensure_logged_in())); self.current_task["search_region"]=sug["search"].to_dict(); self.current_task["verify_regions"]= [sug["header"].to_dict()]; self.refresh_regions(); self.save_current_task(silent=True); self.set_status("已应用建议：搜索结果 + 聊天标题。")
            except Exception as exc:self.root.after(0,lambda:messagebox.showerror("应用建议失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()
    def test_ocr(self):
        try: t=self.current_task["targets"][0]; sr=self.current_task.get("search_region");
        except Exception: messagebox.showerror("无法测试 OCR","请先添加目标并框选搜索区域。",parent=self.root); return
        if not sr: messagebox.showerror("无法测试 OCR","请先框选搜索区域。",parent=self.root); return
        def work():
            try: a=self.ensure(); hwnd=a.search(t["name"]); rows=a.inspect_region(hwnd,RegionInfo.from_dict(sr));
            except Exception as exc:self.root.after(0,lambda:messagebox.showerror("OCR测试失败",str(exc),parent=self.root)); return
            self.root.after(0,lambda:OCRDialog(self.root,rows) if rows else messagebox.showwarning("OCR","没有识别到文字。",parent=self.root)); self.set_status(f"OCR 完成：{len(rows)} 项。")
        threading.Thread(target=work,daemon=True).start()
    def test_click(self):
        try: t=self.current_task["targets"][0]; sr=self.current_task.get("search_region");
        except Exception: messagebox.showerror("无法测试点击","请先添加目标。",parent=self.root); return
        if not sr: messagebox.showerror("无法测试点击","请先框选搜索区域。",parent=self.root); return
        def work():
            try:a=self.ensure(); hwnd=a.search(t["name"]); item,score=a.click_target(hwnd,RegionInfo.from_dict(sr),t["name"],t.get("type","auto")); self.set_status(f"测试点击成功：{item.text} / {score:.1f}；没有发送消息。")
            except Exception as exc:self.root.after(0,lambda:messagebox.showerror("测试点击失败",str(exc),parent=self.root))
        threading.Thread(target=work,daemon=True).start()
    def save_adv(self):
        try:self.settings["ocr_retry_count"]=max(1,min(10,int(self.retry.get()))); self.settings["send_wait"]=max(.2,min(3,float(self.wait.get()))); save_settings(self.settings); self.automation=None; self.set_status("高级设置已保存。")
        except Exception as exc: messagebox.showerror("保存失败",str(exc),parent=self.root)
    def apply_theme(self, name=None):
        name = name or self.settings.get("theme","浅色"); c=THEMES.get(name,THEMES["浅色"]); self.style.configure("TFrame",background=c["bg"]); self.style.configure("TLabelframe",background=c["bg"],foreground=c["fg"]); self.style.configure("TLabelframe.Label",background=c["bg"],foreground=c["fg"]); self.style.configure("TLabel",background=c["bg"],foreground=c["fg"]); self.style.configure("TNotebook",background=c["bg"]); self.style.configure("TButton",padding=(10,6)); self.style.configure("Treeview",rowheight=30,background=c["card"],fieldbackground=c["card"],foreground=c["fg"]); self.root.configure(bg=c["bg"])
    def apply_theme_ui(self): self.settings["theme"]=self.theme.get(); save_settings(self.settings); self.apply_theme(); self.set_status(f"主题已切换为：{self.theme.get()}。")
    def choose_banner(self):
        p=filedialog.askopenfilename(parent=self,title="选择顶部装饰图片",filetypes=[("图片","*.png *.jpg *.jpeg *.webp *.bmp"),("所有文件","*.*")]);
        if p:self.settings["banner_image"]=p;save_settings(self.settings);self.set_status("顶部图片已保存（当前作为外观预留）。")
    def clear_banner(self):self.settings["banner_image"]="";save_settings(self.settings);self.set_status("顶部图片已清除。")
    def send_all_now(self):
        if not self.save_current_task(silent=False):return
        jobs=[(i,t) for i,t in enumerate(self.current_task.get("targets",[])) if t.get("enabled",True)]
        threading.Thread(target=self.execute_job_list,args=(jobs,),daemon=True).start()
    def execute_job_list(self,jobs):
        try:
            a=self.ensure(); sr=RegionInfo.from_dict(self.current_task["search_region"]); vr=[RegionInfo.from_dict(x) for x in self.current_task.get("verify_regions",[])];
            for idx,t in jobs:
                try:
                    a.run_single(t,sr,vr,bool(self.current_task.get("verify_target",True)),bool(self.current_task.get("continue_on_error",False))); self.set_status(f"目标‘{t.get('name','')}’发送完成。")
                except Exception as exc:
                    self.set_status(f"目标‘{t.get('name','')}’发送失败：{exc}");
                    if not self.current_task.get("continue_on_error",False):raise
            self.root.after(0,lambda:messagebox.showinfo("发送完成","全部选定目标处理完成。",parent=self.root))
        except Exception as exc:self.root.after(0,lambda:messagebox.showerror("发送失败",str(exc),parent=self.root))
    def start_all_schedules(self):
        if not self.save_current_task(silent=False):return
        system_count=0; app_jobs=[]; errors=[]
        if getattr(sys,"frozen",False): exe=sys.executable
        else: exe=None
        for idx,t in enumerate(self.current_task.get("targets",[])):
            s=t.get("schedule",{}); dtxt=s.get("datetime","")
            if not t.get("enabled",True) or s.get("mode")!="once" or not dtxt:continue
            try: when=datetime.strptime(dtxt,"%Y-%m-%d %H:%M:%S")
            except Exception: errors.append(f"{t.get('name','')}: 时间格式错误"); continue
            try:
                self.cancel_target_schedule(t,silent=True)
                if t.get("scheduler_mode")=="system":
                    if not exe: raise RuntimeError("系统任务需要先打包为 EXE。")
                    t["system_task_name"]=create_one_shot_task(self.current_task["id"],idx,when,exe); system_count+=1
                else: app_jobs.append((f"{self.current_task['id']}:{idx}",when))
            except Exception as exc: errors.append(f"{t.get('name','')}: {exc}")
        if app_jobs:
            try:self.scheduler.start(app_jobs)
            except Exception as exc:errors.append(str(exc))
        self.save_current_task(silent=True); self.refresh_targets(); count=len(app_jobs)+system_count; self.schedule_status.set(f"已启动 {count} 个定时目标"); self.set_status(self.schedule_status.get());
        if errors:messagebox.showwarning("部分定时未启动","\n".join(errors),parent=self.root)
    def execute_scheduled_job(self,job_id):
        try:
            task_id,idx_s=job_id.split(":",1); idx=int(idx_s); task=next((x for x in self.tasks if x.get("id")==task_id),None)
            if not task or idx>=len(task.get("targets",[])):raise RuntimeError("定时目标不存在。")
            t=task["targets"][idx]; a=self.ensure(); a.run_single(t,RegionInfo.from_dict(task["search_region"]),[RegionInfo.from_dict(x) for x in task.get("verify_regions",[])],bool(task.get("verify_target",True)),bool(task.get("continue_on_error",False))); self.set_status(f"定时目标‘{t.get('name','')}’执行完成。")
            t["schedule"]={"mode":"now","datetime":""}; save_tasks_file(self.tasks)
        except Exception as exc: self.set_status(f"应用内定时目标执行失败：{exc}")
    def cancel_target_schedule(self,t,silent=False):
        name=t.get("system_task_name","")
        if name:
            try:delete_task(name)
            except Exception as exc:
                if not silent:messagebox.showwarning("取消失败",str(exc),parent=self.root)
            t["system_task_name"]=""
        if t.get("scheduler_mode")=="system":t["scheduler_mode"]="app"
    def cancel_all_schedules(self,silent=False):
        self.scheduler.stop()
        for t in self.current_task.get("targets",[]):
            self.cancel_target_schedule(t,silent=True); t["schedule"]={"mode":"now","datetime":""}
        self.save_current_task(silent=True); self.refresh_targets(); self.schedule_status.set("未启动定时")
        if not silent:self.set_status("当前任务的全部定时已取消。")
    def export_task(self):
        self.save_current_task(silent=True); p=filedialog.asksaveasfilename(parent=self.root,title="导出当前任务",defaultextension=".json",filetypes=[("JSON","*.json")]);
        if p:Path(p).write_text(json.dumps({"schema":2,"app":APP_TITLE,"task":self.current_task},ensure_ascii=False,indent=2),"utf-8");self.set_status("任务已导出。")
    def import_task(self):
        p=filedialog.askopenfilename(parent=self.root,title="导入任务 JSON",filetypes=[("JSON","*.json"),("所有文件","*.*")]);
        if not p:return
        try:
            data=json.loads(Path(p).read_text("utf-8")); incoming=data.get("task") if isinstance(data,dict) else data
            if isinstance(incoming,dict):incoming=[incoming]
            if not isinstance(incoming,list):raise ValueError("没有有效任务。")
            for raw in incoming:
                t=new_task(raw.get("name","导入任务")); t.update(raw); t["id"]=uuid.uuid4().hex; self.tasks.append(t)
            save_tasks_file(self.tasks); self.current_task_id=self.tasks[-1]["id"]; self.load_current_task(); self.set_status(f"已导入 {len(incoming)} 个任务。")
        except Exception as exc:messagebox.showerror("导入失败",str(exc),parent=self.root)
    def on_close(self):
        if self.scheduler.running and not messagebox.askyesno("确认退出","当前有应用内定时目标。退出后它们不会执行。\n\n确定退出吗？",parent=self.root):return
        try:self.save_current_task(silent=True)
        except Exception:pass
        self.scheduler.stop(); self.clear_live_overlay(); self.root.destroy()

if __name__=="__main__":
    if "--run-scheduled" in sys.argv:
        try: tid=sys.argv[sys.argv.index("--task-id")+1]; idx=int(sys.argv[sys.argv.index("--target-index")+1])
        except Exception as exc: raise SystemExit(f"缺少系统任务参数：{exc}")
        from task_runner import run_task; run_task(tid,idx); raise SystemExit(0)
    root=tk.Tk(); App(root); root.mainloop()
