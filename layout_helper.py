# -*- coding: utf-8 -*-
"""微信 4.x 常见布局建议器。搜索结果与聊天标题分开保存。"""
from __future__ import annotations
from area_selector import RegionInfo

def suggest_regions(client_rect):
    _left, _top, w, h = client_rect
    return {
        # 搜索结果区域：保持上一版验证过的宽度和位置，不框顶部搜索输入框。
        "search": RegionInfo(
            x=max(0, int(w * 0.075)),
            y=max(0, int(h * 0.125)),
            width=max(320, int(w * 0.34)),
            height=max(380, int(h * 0.82)),
            base_client_width=int(w),
            base_client_height=int(h),
        ),
        # 聊天标题区域：整体向左、向下恢复，宽度略放大，允许与搜索区域重叠。
        # 两个区域允许重叠，不需要刻意避开。
        "header": RegionInfo(
            x=max(0, int(w * 0.30)),
            y=max(0, int(h * 0.065)),
            width=max(320, int(w * 0.34)),
            height=max(44, int(h * 0.055)),
            base_client_width=int(w),
            base_client_height=int(h),
        ),
    }
