# -*- coding: utf-8 -*-
"""RapidOCR 封装、分类与 OCR 容错候选评分。"""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
from typing import Iterable, List, Optional, Tuple


@dataclass
class OCRItem:
    text: str
    box: Tuple[int, int, int, int]
    score: float
    section: str = "未知"
    center_y: float = 0.0


def normalize_text(text: str) -> str:
    text = text or ""
    return re.sub(r"[\s\u3000\-–—_·•:：()（）【】\[\]{}<>《》'\"`~!！?？,，.。]", "", text).lower()


class OCREngine:
    def __init__(self):
        try:
            from rapidocr import RapidOCR
        except Exception as exc:
            raise RuntimeError(
                "RapidOCR 导入失败。请先运行：python -m pip install -r requirements.txt\n"
                f"原始错误：{exc}"
            ) from exc
        self.engine = RapidOCR()

    @staticmethod
    def _to_box(box) -> Tuple[int, int, int, int]:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        return round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))

    def read(self, image) -> List[OCRItem]:
        result = self.engine(image)
        if result is None:
            return []
        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None and isinstance(result, tuple):
            for item in result:
                if hasattr(item, "boxes"):
                    boxes = getattr(item, "boxes", None)
                    txts = getattr(item, "txts", None)
                    scores = getattr(item, "scores", None)
                    break
        if boxes is None or txts is None:
            return []
        output: List[OCRItem] = []
        for i, text in enumerate(txts):
            if i >= len(boxes):
                break
            raw_box = boxes[i]
            score = float(scores[i]) if scores is not None and i < len(scores) else 0.0
            x1, y1, x2, y2 = self._to_box(raw_box)
            output.append(OCRItem(str(text).strip(), (x1, y1, x2, y2), score, center_y=(y1+y2)/2))
        return output

    @staticmethod
    def assign_sections(items: Iterable[OCRItem], labels: Iterable[str]) -> List[OCRItem]:
        items = list(items)
        norm_labels = {normalize_text(x) for x in labels}
        label_items = [i for i in items if normalize_text(i.text) in norm_labels]
        for item in items:
            candidates = [
                lab for lab in label_items
                if lab.center_y <= item.center_y
                and (item.center_y - lab.center_y) < 300
                and lab.box[0] <= item.box[0] + 300
            ]
            item.section = min(candidates, key=lambda x: item.center_y - x.center_y).text if candidates else "未知"
        return items

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        na, nb = normalize_text(a), normalize_text(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        if na in nb:
            return max(0.7, len(na) / len(nb) * 0.95)
        if nb in na:
            return max(0.68, len(nb) / len(na) * 0.90)
        ratio = difflib.SequenceMatcher(None, na, nb).ratio()
        sa, sb = set(na), set(nb)
        jaccard = len(sa & sb) / max(1, len(sa | sb))
        return max(ratio * 0.88, jaccard * 0.85)

    @staticmethod
    def _combined_candidates(items: List[OCRItem]) -> List[OCRItem]:
        """补足 OCR 把一个名称拆成相邻两块的情况。"""
        out = list(items)
        sorted_items = sorted(items, key=lambda x: (x.box[1], x.box[0]))
        for i, a in enumerate(sorted_items):
            ax1, ay1, ax2, ay2 = a.box
            for b in sorted_items[i+1:i+5]:
                bx1, by1, bx2, by2 = b.box
                same_row = abs(((ay1+ay2)/2) - ((by1+by2)/2)) <= max(14, min(ay2-ay1, by2-by1) * 0.7)
                gap = bx1 - ax2
                if same_row and 0 <= gap <= 45 and bx1 >= ax1:
                    box = (min(ax1,bx1), min(ay1,by1), max(ax2,bx2), max(ay2,by2))
                    out.append(OCRItem(a.text + b.text, box, min(a.score,b.score), section=a.section, center_y=(box[1]+box[3])/2))
        return out

    def candidates(self, items: Iterable[OCRItem], target: str, target_type: str = "auto") -> List[Tuple[OCRItem, float]]:
        items = self._combined_candidates(list(items))
        ntarget = normalize_text(target)
        type_map = {
            "contact": {"联系人"},
            "group": {"群聊", "群组"},
            "auto": set(),
        }
        allowed = type_map.get(target_type, set())
        blocked = {normalize_text(x) for x in ("最常使用", "联系人", "群聊", "群组", "公众号", "最近使用", "最近聊天")}
        candidates = []
        for item in items:
            ntext = normalize_text(item.text)
            if not ntext or ntext in blocked:
                continue
            sim = self._similarity(item.text, target)
            if sim < 0.60:
                continue
            score = sim * 100 + item.score * 7
            if ntext == ntarget:
                score += 35
            if ntarget and ntext.startswith(ntarget):
                score += 10
            if allowed:
                if normalize_text(item.section) in {normalize_text(x) for x in allowed}:
                    score += 20
                elif normalize_text(item.section) in {normalize_text(x) for x in ("最常使用", "最近使用", "最近聊天", "未知")}:
                    score += 0
                else:
                    score -= 10
            candidates.append((item, score))
        return sorted(candidates, key=lambda x: x[1], reverse=True)

    def find(self, image, target: str, target_type: str = "auto") -> Optional[Tuple[OCRItem, float]]:
        from config import SECTION_LABELS
        items = self.read(image)
        if not items:
            return None
        items = self.assign_sections(items, SECTION_LABELS)
        candidates = self.candidates(items, target, target_type)
        return candidates[0] if candidates else None
