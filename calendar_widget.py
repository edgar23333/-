# -*- coding: utf-8 -*-
"""轻量级 Tk 日历：不额外依赖第三方库。"""

from __future__ import annotations

import calendar
from datetime import date
import tkinter as tk
from tkinter import ttk


class MonthCalendar(ttk.Frame):
    def __init__(self, parent, initial: date, on_select):
        super().__init__(parent)
        self.on_select = on_select
        self.year = initial.year
        self.month = initial.month
        self.selected = initial
        self.build()
        self.render()

    def build(self):
        nav = ttk.Frame(self)
        nav.pack(fill="x", pady=(0, 6))
        ttk.Button(nav, text="‹ 上个月", width=10, command=lambda: self.move_month(-1)).pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Label(nav, textvariable=self.title_var, font=("Microsoft YaHei UI", 13, "bold")).pack(side="left", expand=True)
        ttk.Button(nav, text="下个月 ›", width=10, command=lambda: self.move_month(1)).pack(side="right")

        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(fill="both", expand=True)
        for c, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            ttk.Label(self.grid_frame, text=name, anchor="center").grid(row=0, column=c, sticky="nsew", pady=(0, 4))
            self.grid_frame.columnconfigure(c, weight=1)
        for r in range(1, 7):
            self.grid_frame.rowconfigure(r, weight=1)

    def move_month(self, delta: int):
        self.month += delta
        if self.month < 1:
            self.month = 12
            self.year -= 1
        elif self.month > 12:
            self.month = 1
            self.year += 1
        self.render()

    def render(self):
        for widget in self.grid_frame.winfo_children()[7:]:
            widget.destroy()
        self.title_var.set(f"{self.year} 年 {self.month} 月")
        weeks = calendar.monthcalendar(self.year, self.month)
        for row_idx, week in enumerate(weeks, 1):
            for col_idx, day_num in enumerate(week):
                if day_num == 0:
                    ttk.Label(self.grid_frame, text="").grid(row=row_idx, column=col_idx, sticky="nsew", padx=2, pady=2)
                    continue
                d = date(self.year, self.month, day_num)
                is_selected = d == self.selected
                btn = tk.Button(
                    self.grid_frame,
                    text=str(day_num),
                    relief="sunken" if is_selected else "flat",
                    bd=1,
                    font=("Microsoft YaHei UI", 11, "bold" if is_selected else "normal"),
                    command=lambda day=day_num: self.select_day(day),
                )
                btn.grid(row=row_idx, column=col_idx, sticky="nsew", padx=2, pady=2)

    def select_day(self, day_num: int):
        self.selected = date(self.year, self.month, day_num)
        self.render()
        self.on_select(self.selected)
