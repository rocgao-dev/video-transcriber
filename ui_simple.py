# -*- coding: utf-8 -*-
"""视频转写逐字稿 —— 极简桌面界面（单窗口）。

特点:
    * 只依赖 Python 标准库 tkinter，界面本身极简。
    * 真正的转写引擎 transcribe.py 需要 faster-whisper 等依赖，
      本界面会自动探测「含依赖的 Python 解释器」并以子进程方式调用它。
    * 全程本地处理：不联网、不上传、不消耗任何 token。

启动:
    双击同目录下的「启动简单UI.bat」即可。
    也可用任意带 tkinter 的 Python 直接运行本文件。
    转写引擎的解释器可写入 engine_python.txt / python_path.txt，
    或用环境变量 VIDEO_TRANSCRIBER_PY 指定。
"""
from __future__ import annotations

import glob
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# --------------------------------------------------------------------------- #
# 路径与常量
# --------------------------------------------------------------------------- #
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(TOOL_DIR, "transcribe.py")

_VIDEO_FILETYPES = [
    ("视频/音频文件", "*.mp4 *.mkv *.mov *.avi *.flv *.wmv *.webm *.ts *.m4v "
                     "*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.opus *.wma"),
    ("所有文件", "*.*"),
]

# 段行形如 "[   12.3] 文本"
_SEG_RE = re.compile(r"^\[\s*\d")

# 用 find_spec 快速判断模块是否可导入（不真正加载，避免拖慢界面）
_FIND_SPEC_CODE = (
    "import importlib.util as u,sys;"
    "sys.exit(0 if u.find_spec('faster_whisper') else 1)"
)


def _config_engine_python():
    """从同目录配置文件读取用户显式指定的引擎解释器（可选）。"""
    for name in ("engine_python.txt", "python_path.txt"):
        p = os.path.join(TOOL_DIR, name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip().strip('"')
                    if line and not line.startswith("#"):
                        return line
        except Exception:
            pass
    return None


def _iter_engine_python_candidates():
    """按优先级返回可能含 faster-whisper 的解释器路径（去重、跳过商店占位符）。"""
    cands = []

    def add(p):
        if not p:
            return
        try:
            p = os.path.abspath(os.path.expanduser(str(p).strip()))
        except Exception:
            return
        if "windowsapps" in p.lower():        # 跳过 Microsoft Store 占位符
            return
        if p not in cands:
            cands.append(p)

    add(os.environ.get("VIDEO_TRANSCRIBER_PY"))
    add(_config_engine_python())
    add(os.path.join(TOOL_DIR, "python", "python.exe"))     # 自带便携版（可选）
    add(os.path.join(TOOL_DIR, "runtime", "python.exe"))
    add(shutil.which("python"))
    add(shutil.which("python3"))
    try:                                                    # py 启动器
        r = subprocess.run(["py", "-3", "-c", "import sys;print(sys.executable)"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            add(r.stdout.strip().splitlines()[0])
    except Exception:
        pass
    # 常见安装位置
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    patterns = [
        os.path.join(local, "Programs", "Python", "Python3*", "python.exe") if local else "",
        os.path.join(pf, "Python3*", "python.exe"),
        r"C:\Python3*\python.exe",
    ]
    for pat in patterns:
        if not pat:
            continue
        try:
            for p in sorted(glob.glob(pat), reverse=True):
                add(p)
        except Exception:
            pass
    return cands


def _has_faster_whisper(py):
    """快速判断某解释器是否装了 faster-whisper。"""
    try:
        r = subprocess.run([py, "-c", _FIND_SPEC_CODE], capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def find_engine_python():
    """定位用于运行 transcribe.py 的解释器（需含 faster-whisper）。

    查找顺序：环境变量 VIDEO_TRANSCRIBER_PY → 同目录 engine_python.txt /
    python_path.txt → 自带 python\\ → PATH → py 启动器 → 常见安装位置，
    并逐个校验能否 import faster-whisper；都不满足时返回第一个存在的解释器
    （便于界面给出更准确提示），完全没有则返回 None。
    """
    existing = [p for p in _iter_engine_python_candidates() if os.path.isfile(p)]
    for p in existing:
        if _has_faster_whisper(p):
            return p
    return existing[0] if existing else None


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.media = ""          # 选中的媒体文件
        self.proc = None         # 子进程句柄
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.tmp_out = ""        # 引擎输出临时文件
        self.running = False
        self.seg_count = 0

        root.title("视频转写逐字稿 · 本地 · 零 token")
        root.geometry("760x560")
        root.minsize(640, 440)

        self._build_ui()
        self.root.after(100, self._poll)

    # ---------------- UI ---------------- #
    def _build_ui(self):
        pad = {"padx": 8, "pady": 5}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="待转写文件:").pack(side="left")
        self.file_var = tk.StringVar(value="（尚未选择）")
        ttk.Entry(top, textvariable=self.file_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(8, 8)
        )
        self.btn_pick = ttk.Button(top, text="选择文件…", command=self.on_pick)
        self.btn_pick.pack(side="left")

        mid = ttk.Frame(self.root)
        mid.pack(fill="x", **pad)
        self.btn_start = ttk.Button(mid, text="开始转写", command=self.on_start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(mid, text="停止", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 16))
        self.ts_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(mid, text="每句前加时间戳", variable=self.ts_var).pack(side="left")

        prog = ttk.Frame(self.root)
        prog.pack(fill="x", **pad)
        self.bar = ttk.Progressbar(prog, mode="indeterminate")
        self.bar.pack(fill="x", side="left", expand=True)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(prog, textvariable=self.status_var, width=28, anchor="e").pack(
            side="left", padx=(8, 0)
        )

        ttk.Label(self.root, text="逐字稿:").pack(anchor="w", padx=8)
        self.text = ScrolledText(self.root, wrap="word", font=("Microsoft YaHei UI", 10))
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        bot = ttk.Frame(self.root)
        bot.pack(fill="x", **pad)
        self.btn_save = ttk.Button(bot, text="保存为 TXT…", command=self.on_save, state="disabled")
        self.btn_save.pack(side="left")
        self.btn_copy = ttk.Button(bot, text="复制全部", command=self.on_copy)
        self.btn_copy.pack(side="left", padx=(8, 0))
        ttk.Label(
            bot, text="全程本地处理，不联网、不消耗 token",
            foreground="#888",
        ).pack(side="right")

    # ---------------- 事件 ---------------- #
    def on_pick(self):
        if self.running:
            return
        f = filedialog.askopenfilename(title="选择要转写的视频/音频", filetypes=_VIDEO_FILETYPES)
        if f:
            self.media = f
            self.file_var.set(f)
            self._set_status("已选择文件，点击「开始转写」")

    def on_start(self):
        if self.running:
            return
        if not self.media or not os.path.isfile(self.media):
            messagebox.showwarning("提示", "请先选择要转写的视频/音频文件。")
            return

        engine_py = find_engine_python()
        if not engine_py:
            messagebox.showerror(
                "找不到 Python",
                "未在本机找到 Python 解释器。\n\n"
                "请先安装 Python 3.9+，再双击同目录的「安装依赖.bat」。",
            )
            return
        if not _has_faster_whisper(engine_py):
            messagebox.showerror(
                "缺少转写依赖",
                "已找到 Python：\n%s\n\n但它还没安装转写依赖（faster-whisper 等）。\n\n"
                "请双击同目录的「安装依赖.bat」，或手动执行：\n"
                "    pip install -r requirements.txt" % engine_py,
            )
            return
        if not os.path.isfile(ENGINE):
            messagebox.showerror("缺少引擎", "未找到 transcribe.py：\n" + ENGINE)
            return

        fd, self.tmp_out = tempfile.mkstemp(prefix="vt_ui_", suffix=".txt")
        os.close(fd)
        fmt = "ts" if self.ts_var.get() else "txt"
        cmd = [engine_py, "-u", ENGINE, self.media, "-f", fmt, "-o", self.tmp_out]

        self.text.delete("1.0", "end")
        self.seg_count = 0
        self.running = True
        self.btn_start.configure(state="disabled")
        self.btn_pick.configure(state="disabled")
        self.btn_save.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.bar.start(12)
        self._set_status("正在启动转写…")

        threading.Thread(target=self._worker, args=(cmd,), daemon=True).start()

    def on_stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self._set_status("已请求停止…")

    def on_save(self):
        content = self.text.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("提示", "当前没有可保存的内容。")
            return
        default = os.path.splitext(os.path.basename(self.media or "逐字稿"))[0] + ".txt"
        f = filedialog.asksaveasfilename(
            title="保存逐字稿", defaultextension=".txt",
            initialfile=default, filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not f:
            return
        try:
            with open(f, "w", encoding="utf-8", newline="\n") as fp:
                fp.write(content + "\n")
            self._set_status("已保存: " + os.path.basename(f))
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def on_copy(self):
        content = self.text.get("1.0", "end").strip()
        if not content:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self._set_status("已复制到剪贴板")

    # ---------------- 后台转写 ---------------- #
    def _worker(self, cmd):
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.proc = subprocess.Popen(
                cmd, cwd=TOOL_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=flags,
            )
            for line in self.proc.stderr:            # 逐行读取状态/分段
                line = line.rstrip("\r\n")
                if not line:
                    continue
                if _SEG_RE.match(line):
                    self.q.put(("seg", line))
                else:
                    self.q.put(("status", line))
            self.proc.wait()
            rc = self.proc.returncode
            stdout = self.proc.stdout.read() if self.proc.stdout else ""
            self.q.put(("done", rc, stdout.strip()))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "seg":
                    self.seg_count += 1
                    self.text.insert("end", msg[1] + "\n")
                    self.text.see("end")
                    self._set_status(f"转写中… 已 {self.seg_count} 段")
                elif kind == "status":
                    self._set_status(msg[1])
                elif kind == "done":
                    self._finish(msg[1], msg[2])
                elif kind == "error":
                    self._fail(msg[1])
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll)

    def _finish(self, rc, stdout):
        self.running = False
        self.bar.stop()
        self.btn_start.configure(state="normal")
        self.btn_pick.configure(state="normal")
        self.btn_stop.configure(state="disabled")

        if rc != 0:
            self._fail("转写未完成（退出码 %s），请检查文件是否可读。" % rc)
            return
        try:
            with open(self.tmp_out, "r", encoding="utf-8") as fp:
                content = fp.read()
        except Exception:
            content = self.text.get("1.0", "end").strip()
        content = content.strip()
        self.text.delete("1.0", "end")
        self.text.insert("end", content)
        self.btn_save.configure(state="normal")
        self._set_status(f"完成！共 {self.seg_count} 段，可保存或复制")

    def _fail(self, msg):
        self.running = False
        self.proc = None
        self.bar.stop()
        self.btn_start.configure(state="normal")
        self.btn_pick.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._set_status("出错了")
        messagebox.showerror("转写失败", msg)

    def _set_status(self, s):
        self.status_var.set(s[:40])


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback as _tb
        _t = _tb.format_exc()
        try:
            with open(os.path.join(TOOL_DIR, "ui_error.log"), "w", encoding="utf-8") as _f:
                _f.write(_t + "\n")
        except Exception:
            pass
        try:
            import tkinter as _tk
            import tkinter.messagebox as _mb
            _r = _tk.Tk(); _r.withdraw()
            _mb.showerror("视频转写工具 · 启动失败", _t[-1800:])
            _r.destroy()
        except Exception:
            pass
        sys.exit(1)