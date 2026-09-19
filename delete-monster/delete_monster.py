#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
怪兽删除确认器
用法：python delete_monster.py <要删除的文件路径>
      把文件拖到 delete_monster.exe 上也会触发。
效果：弹出怪兽确认窗 → 点“是” → 爆炸 → 怪兽飞出屏幕 → 文件进回收站。
"""

import sys
import os
import random
import math
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk


# ----------------------------------------------------------------------
# Windows 回收站删除
# ----------------------------------------------------------------------
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def resource_path(rel):
    """兼容 PyInstaller 单文件打包的资源路径。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def move_to_recycle_bin(path):
    """把文件移到回收站，不弹确认框。"""
    if not os.path.exists(path):
        return False
    fop = SHFILEOPSTRUCTW()
    fop.hwnd = None
    fop.wFunc = 3  # FO_DELETE
    # pFrom 必须以双空字符结尾，且支持多文件以空字符分隔
    fop.pFrom = path + "\0\0"
    fop.pTo = None
    fop.fFlags = 0x0040 | 0x0010  # FOF_ALLOWUNDO | FOF_NOCONFIRMATION
    fop.fAnyOperationsAborted = False
    fop.hNameMappings = None
    fop.lpszProgressTitle = None
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fop))
    return rc == 0 and not fop.fAnyOperationsAborted


# ----------------------------------------------------------------------
# 画圆角矩形辅助
# ----------------------------------------------------------------------
def rounded_rect_points(x, y, w, h, r):
    """返回一个近似圆角矩形的顺时针多边形点列表。"""
    pts = []
    # 右上角弧
    for i in range(10, 0, -1):
        a = math.radians(i * 9)
        pts.append((x + w - r + math.cos(a) * r, y + h - r + math.sin(a) * r))
    # 右下角弧
    for i in range(0, 10):
        a = math.radians(i * 9)
        pts.append((x + w - r + math.cos(a) * r, y + r + math.sin(a) * r))
    # 左下角弧
    for i in range(10, 0, -1):
        a = math.radians(180 - i * 9)
        pts.append((x + r + math.cos(a) * r, y + r + math.sin(a) * r))
    # 左上角弧
    for i in range(0, 10):
        a = math.radians(180 - i * 9)
        pts.append((x + r + math.cos(a) * r, y + h - r + math.sin(a) * r))
    return pts


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------
class MonsterDeleteApp:
    DIALOG_W = 520
    DIALOG_H = 340
    BG = "#ff00ff"  # 透明色键

    def __init__(self, target_path):
        self.target_path = os.path.abspath(target_path)
        self.filename = os.path.basename(self.target_path)

        self.root = tk.Tk()
        self.root.title("怪兽删除确认器")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", self.BG)
        self.root.configure(bg=self.BG)

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.sw, self.sh = sw, sh
        self.root.geometry(f"{sw}x{sh}+0+0")

        self.cv = tk.Canvas(
            self.root,
            width=sw,
            height=sh,
            bg=self.BG,
            highlightthickness=0,
        )
        self.cv.pack()

        self.dx = (sw - self.DIALOG_W) // 2
        self.dy = (sh - self.DIALOG_H) // 2

        self._draw_scene()
        self._bind_events()

    # ------------------------------------------------------------------
    # 绘制静态场景
    # ------------------------------------------------------------------
    def _draw_scene(self):
        cx = self.sw // 2
        cy = self.sh // 2
        dx, dy = self.dx, self.dy
        dw, dh = self.DIALOG_W, self.DIALOG_H

        # 对话框阴影
        shadow = rounded_rect_points(dx + 8, dy + 8, dw, dh, 24)
        self.cv.create_polygon(
            shadow, fill="#000000", outline="", stipple="gray50", tags="shadow"
        )

        # 对话框背景
        dialog = rounded_rect_points(dx, dy, dw, dh, 24)
        self.cv.create_polygon(dialog, fill="#3498db", outline="#2980b9", width=2, tags="dialog")

        # 怪兽图（居中偏左）
        self._draw_monster_image(cx - 100, cy + 20)

        # 文件图标（居中偏右）
        self._draw_file_icon(cx + 60, cy - 40, self.filename)

        # 按钮
        self._draw_button(
            cx - 150, dy + dh - 70, 120, 44, "是的", tag="btn_yes"
        )
        self._draw_button(
            cx + 30, dy + dh - 70, 160, 44, "嘤嘤嘤就是这个", tag="btn_cute"
        )

        # 气泡对话框（上方）
        self._draw_speech_bubble(cx - 20, dy - 80, "oi，是这个吗？")

    def _draw_monster(self, cx, cy):
        """用 canvas 形状画一只站立的怪兽，所有部件打 tag 'monster'。"""
        s = 1.0  # 缩放基准
        # 身体（棕色椭圆）
        self.cv.create_oval(
            cx - 55 * s, cy + 10 * s, cx + 55 * s, cy + 110 * s,
            fill="#B5651D", outline="#8B4513", width=2, tags="monster"
        )
        # 肚皮（浅棕椭圆）
        self.cv.create_oval(
            cx - 30 * s, cy + 35 * s, cx + 30 * s, cy + 95 * s,
            fill="#DEB887", outline="", tags="monster"
        )
        # 左腿
        self.cv.create_line(
            cx - 25 * s, cy + 105 * s, cx - 30 * s, cy + 150 * s,
            fill="#B5651D", width=14, tags="monster"
        )
        self.cv.create_oval(
            cx - 42 * s, cy + 145 * s, cx - 18 * s, cy + 165 * s,
            fill="#B5651D", outline="#8B4513", width=2, tags="monster"
        )
        # 右腿
        self.cv.create_line(
            cx + 25 * s, cy + 105 * s, cx + 30 * s, cy + 150 * s,
            fill="#B5651D", width=14, tags="monster"
        )
        self.cv.create_oval(
            cx + 18 * s, cy + 145 * s, cx + 42 * s, cy + 165 * s,
            fill="#B5651D", outline="#8B4513", width=2, tags="monster"
        )
        # 尾巴
        tail = [
            cx - 50 * s, cy + 80 * s,
            cx - 95 * s, cy + 60 * s,
            cx - 85 * s, cy + 40 * s,
            cx - 50 * s, cy + 55 * s,
        ]
        self.cv.create_polygon(tail, fill="#B5651D", outline="#8B4513", width=2, tags="monster")

        # 头（椭圆）
        self.cv.create_oval(
            cx - 45 * s, cy - 70 * s, cx + 45 * s, cy + 20 * s,
            fill="#B5651D", outline="#8B4513", width=2, tags="monster"
        )
        # 嘴巴
        self.cv.create_arc(
            cx - 25 * s, cy - 25 * s, cx + 25 * s, cy + 15 * s,
            start=0, extent=-180, style="arc", outline="#5D4037", width=3, tags="monster"
        )
        # 左眼白
        self.cv.create_oval(
            cx - 28 * s, cy - 45 * s, cx - 8 * s, cy - 20 * s,
            fill="white", outline="", tags="monster"
        )
        # 左眼珠
        self.cv.create_oval(
            cx - 22 * s, cy - 40 * s, cx - 14 * s, cy - 28 * s,
            fill="black", outline="", tags="monster"
        )
        # 右眼白
        self.cv.create_oval(
            cx + 8 * s, cy - 45 * s, cx + 28 * s, cy - 20 * s,
            fill="white", outline="", tags="monster"
        )
        # 右眼珠
        self.cv.create_oval(
            cx + 14 * s, cy - 40 * s, cx + 22 * s, cy - 28 * s,
            fill="black", outline="", tags="monster"
        )
        # 角
        horn = [
            cx - 5 * s, cy - 65 * s,
            cx + 5 * s, cy - 65 * s,
            cx + 12 * s, cy - 100 * s,
            cx - 12 * s, cy - 100 * s,
        ]
        self.cv.create_polygon(horn, fill="#555555", outline="#333333", width=2, tags="monster")

        # 左臂（下垂）
        self.cv.create_line(
            cx - 45 * s, cy + 35 * s, cx - 80 * s, cy + 75 * s,
            fill="#B5651D", width=12, tags="monster"
        )
        self.cv.create_oval(
            cx - 90 * s, cy + 70 * s, cx - 70 * s, cy + 90 * s,
            fill="#B5651D", outline="#8B4513", width=2, tags="monster"
        )
        # 右臂（抬起指向文件）
        self.cv.create_line(
            cx + 40 * s, cy + 10 * s, cx + 110 * s, cy - 30 * s,
            fill="#B5651D", width=12, tags="monster"
        )
        self.cv.create_oval(
            cx + 105 * s, cy - 40 * s, cx + 125 * s, cy - 20 * s,
            fill="#B5651D", outline="#8B4513", width=2, tags="monster"
        )

    def _draw_monster_image(self, cx, cy):
        """加载真实怪兽图（monster.webp）并居中显示。找不到则回退到手绘。"""
        img_path = resource_path("monster.webp")
        if not os.path.exists(img_path):
            self._draw_monster(cx, cy)
            return

        try:
            img = Image.open(img_path).convert("RGBA")
            max_h = 220
            ratio = max_h / img.height
            new_w, new_h = int(img.width * ratio), max_h
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.ANTIALIAS  # Pillow < 9
            img = img.resize((new_w, new_h), resample)
            self.monster_photo = ImageTk.PhotoImage(img)
            self.cv.create_image(
                cx, cy, image=self.monster_photo, anchor="center", tags="monster"
            )
        except Exception as e:
            print("加载怪兽图失败:", e)
            self._draw_monster(cx, cy)

    def _draw_file_icon(self, x, y, filename):
        """画一个简易文件图标 + 文件名。"""
        w, h = 64, 80
        # 图标主体
        self.cv.create_rectangle(
            x - w // 2, y - h // 2, x + w // 2, y + h // 2,
            fill="white", outline="#bdc3c7", width=2, tags="fileicon"
        )
        # 折角
        fold = [
            x + w // 2 - 18, y - h // 2,
            x + w // 2, y - h // 2 + 18,
            x + w // 2, y - h // 2,
        ]
        self.cv.create_polygon(fold, fill="#ecf0f1", outline="#bdc3c7", width=1, tags="fileicon")
        # 文件类型大字
        ext = os.path.splitext(filename)[1].lstrip(".").upper() or "FILE"
        self.cv.create_text(
            x, y + 5, text=ext[:4], font=("Microsoft YaHei", 14, "bold"),
            fill="#3498db", tags="fileicon"
        )
        # 文件名
        display = filename if len(filename) <= 14 else filename[:12] + "..."
        self.cv.create_text(
            x, y + h // 2 + 16, text=display, font=("Microsoft YaHei", 12),
            fill="white", tags="filename"
        )

    def _draw_button(self, x, y, w, h, text, tag):
        r = h // 2
        pts = rounded_rect_points(x, y, w, h, r)
        bid = self.cv.create_polygon(
            pts, fill="#ffffff", outline="#ecf0f1", width=2, tags=tag
        )
        tid = self.cv.create_text(
            x + w // 2, y + h // 2, text=text,
            font=("Microsoft YaHei", 12), fill="#2c3e50", tags=tag
        )
        self.cv.tag_bind(tag, "<Button-1>", lambda e: self._on_confirm())
        self.cv.tag_bind(tag, "<Enter>", lambda e: self.cv.itemconfig(bid, fill="#f0f0f0"))
        self.cv.tag_bind(tag, "<Leave>", lambda e: self.cv.itemconfig(bid, fill="#ffffff"))

    def _draw_speech_bubble(self, cx, y, text):
        """画上方气泡文字。"""
        # 估算文字尺寸：tkinter 没有直接测文字的便捷方法，先占位
        pad_x, pad_y = 16, 10
        # 用临时 label 测？简单用固定尺寸
        text_w = 160
        text_h = 34
        x1, y1 = cx - text_w // 2, y - text_h // 2
        x2, y2 = cx + text_w // 2, y + text_h // 2
        pts = rounded_rect_points(x1, y1, text_w, text_h, 16)
        # 下方小三角指向怪兽头顶
        pts += [(cx - 10, y2), (cx, y2 + 12), (cx + 10, y2)]
        self.cv.create_polygon(pts, fill="white", outline="#ecf0f1", width=2, tags="bubble")
        self.cv.create_text(
            cx, y, text=text, font=("Microsoft YaHei", 13),
            fill="#2c3e50", tags="bubble"
        )

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _bind_events(self):
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def _on_confirm(self):
        """点击任意‘是’按钮：开始动画并删除文件。"""
        if getattr(self, "_confirmed", False):
            return
        self._confirmed = True

        # 先隐藏 UI，保留怪兽和文件图标
        for tag in ("dialog", "shadow", "btn_yes", "btn_cute", "bubble"):
            self.cv.delete(tag)

        # 移动文件到回收站（真删）
        try:
            move_to_recycle_bin(self.target_path)
        except Exception as e:
            print("删除失败:", e)

        # 动画序列
        self._explode()
        self.root.after(300, self._fly_away)
        self.root.after(1400, self.root.destroy)

    # ------------------------------------------------------------------
    # 动画
    # ------------------------------------------------------------------
    def _explode(self):
        """在文件图标位置生成爆炸粒子。"""
        cx = self.sw // 2 + 60
        cy = self.sh // 2 - 40
        colors = ["#e74c3c", "#f39c12", "#f1c40f", "#95a5a6", "#2c3e50"]
        self.particles = []
        for _ in range(45):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(2, 10)
            px = cx + random.uniform(-10, 10)
            py = cy + random.uniform(-10, 10)
            r = random.randint(3, 10)
            color = random.choice(colors)
            pid = self.cv.create_oval(px - r, py - r, px + r, py + r, fill=color, outline="", tags="explosion")
            self.particles.append({
                "id": pid, "x": px, "y": py,
                "vx": math.cos(angle) * speed, "vy": math.sin(angle) * speed,
                "life": 1.0, "decay": random.uniform(0.03, 0.07)
            })
        self._animate_explosion(0)

    def _animate_explosion(self, frame):
        if frame >= 18:
            self.cv.delete("explosion")
            return
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["vy"] += 0.3  # 重力
            p["life"] -= p["decay"]
            if p["life"] < 0:
                p["life"] = 0
            # 简单淡出：变小
            r = max(1, int(6 * p["life"]))
            self.cv.coords(
                p["id"],
                p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r
            )
            # 颜色变暗一点（tk 不支持 alpha，用灰度近似）
            if p["life"] < 0.3:
                self.cv.itemconfig(p["id"], fill="#7f8c8d")
        self.root.after(40, lambda: self._animate_explosion(frame + 1))

    def _fly_away(self):
        """怪兽朝右上角飞走并缩小。"""
        self.fly_frame = 0
        self.fly_total = 24
        self._animate_fly()

    def _animate_fly(self):
        if self.fly_frame >= self.fly_total:
            self.cv.delete("monster")
            return
        t = self.fly_frame / self.fly_total
        # 沿抛物线飞向右上
        dx = 12 * self.fly_frame + 2 * self.fly_frame ** 1.3
        dy = -10 * self.fly_frame - 1.5 * self.fly_frame ** 1.5
        scale = 1.0 - 0.85 * t
        # 获取怪兽当前包围盒中心
        bbox = self.cv.bbox("monster")
        if bbox:
            cx = (bbox[0] + bbox[2]) / 2
            cy = (bbox[1] + bbox[3]) / 2
            self.cv.scale("monster", cx, cy, 0.97, 0.97)
        self.cv.move("monster", dx - getattr(self, "_last_dx", 0), dy - getattr(self, "_last_dy", 0))
        self._last_dx, self._last_dy = dx, dy
        self.fly_frame += 1
        self.root.after(35, self._animate_fly)

    # ------------------------------------------------------------------
    # 运行
    # ------------------------------------------------------------------
    def run(self):
        self.root.mainloop()


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
def main():
    auto = "--auto-confirm" in sys.argv
    if auto:
        sys.argv.remove("--auto-confirm")

    if len(sys.argv) < 2:
        # 无参数时：生成一个临时演示文件并删除它
        demo = os.path.join(os.environ.get("TEMP", "."), "怪兽删除演示.txt")
        with open(demo, "w", encoding="utf-8") as f:
            f.write("这是一份注定要牺牲的演示文件。\n")
        print(f"无文件参数，演示模式：将删除 {demo}")
        path = demo
    else:
        path = sys.argv[1]

    if not os.path.exists(path):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("文件不存在", f"找不到文件：\n{path}")
        root.destroy()
        sys.exit(1)

    app = MonsterDeleteApp(path)
    if auto:
        # 测试模式：自动触发确认，让动画跑完自动退出
        app.root.after(200, app._on_confirm)
    app.run()


if __name__ == "__main__":
    main()
