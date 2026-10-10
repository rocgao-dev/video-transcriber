# -*- coding: utf-8 -*-
"""视频/音频 -> 逐字稿（全本地 faster-whisper，不消耗云端 token）。

命令行用法:
    python transcribe.py <媒体文件> [选项]

常用示例:
    python transcribe.py D:\\video.mp4
    python transcribe.py D:\\video.mp4 -o 逐字稿.txt
    python transcribe.py D:\\video.mp4 --timestamps
    python transcribe.py D:\\video.mp4 -f srt
    python transcribe.py D:\\audio.m4a -f json

支持的输入: 视频 mp4/mkv/mov/avi/flv/wmv/webm/ts/m4v 等
           音频 mp3/m4a/aac/wav/flac/ogg/opus/wma 等
输出格式: txt(逐字稿分段) para(逐字稿自然段) ts(带时间戳) srt vtt json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(TOOL_DIR, "models")
DEFAULT_MODEL_SIZE = "small"
SAMPLE_RATE = 16000

# 额外的模型目录（可选）：用环境变量 VIDEO_TRANSCRIBER_MODEL_DIRS 指定，
# 多个目录用分号（Windows）/冒号（类 Unix）分隔，用于兼容旧的模型存放位置。
LEGACY_MODEL_DIRS = [
    p for p in os.environ.get("VIDEO_TRANSCRIBER_MODEL_DIRS", "").split(os.pathsep) if p
]

SUPPORTED_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".ts", ".m4v", ".mpg", ".mpeg", ".3gp", ".rmvb",
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".amr", ".aiff",
}

# 环境可能给文本文件注入 "# AI生成" 首行，这里统一识别并去除
_AI_HEADER_RE = re.compile(r"^#\s*AI[^\s]*\s*$", re.IGNORECASE)


def _stderr(msg: str) -> None:
    try:
        print(msg, file=sys.stderr, flush=True)
    except Exception:
        pass


def strip_ai_header(text: str) -> str:
    """去除注入的 "# AI生成" 首行（若有），返回清理后的文本。"""
    lines = text.split("\n")
    while lines and _AI_HEADER_RE.match(lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 依赖 / 资源定位
# --------------------------------------------------------------------------- #
def find_ffmpeg() -> str:
    env = os.environ.get("FFMPEG_BINARY")
    if env and os.path.isfile(env):
        return env
    # 工具自带（便于整体拷贝到别的电脑后免安装即用）
    for name in ("ffmpeg.exe", "ffmpeg"):
        local = os.path.join(TOOL_DIR, "bin", name)
        if os.path.isfile(local):
            return local
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    p = shutil.which("ffmpeg")
    if p:
        return p
    raise RuntimeError(
        "未找到 ffmpeg。请任选其一：\n"
        "  1) 把 ffmpeg.exe 放进本工具目录的 bin\\ 下（推荐，免安装）\n"
        "  2) pip install imageio-ffmpeg   （自带 ffmpeg）\n"
        "  3) 安装系统 ffmpeg 并加入 PATH\n"
        "  4) 设置环境变量 FFMPEG_BINARY=C:\\path\\to\\ffmpeg.exe"
    )


def resolve_model_dir(size: str = DEFAULT_MODEL_SIZE, explicit: str | None = None) -> str:
    cands: list[str] = []
    if explicit:
        cands.append(explicit)
    env = os.environ.get("VIDEO_TRANSCRIBER_MODEL")
    if env:
        cands.append(env)
    cands.append(os.path.join(MODELS_DIR, size))
    cands.append(os.path.join(MODELS_DIR, "small"))
    cands.extend(LEGACY_MODEL_DIRS)
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "model.bin")):
            return c
    raise RuntimeError(
        "未找到可用模型（需要包含 model.bin / config.json / tokenizer.json / vocabulary.txt 的目录）。\n"
        "已查找: " + "; ".join(cands) + "\n"
        "请把模型放入 " + os.path.join(MODELS_DIR, size) + "，或用 --model-dir 指定。"
    )


def sanitize_vocab(model_dir: str) -> None:
    """faster-whisper 的 CT2 词表若首行被注入注释，会导致词表 id 整体错位报错。

    这里在加载模型前把注入行剔除（同一进程内完成，避免再次被注入）。
    """
    vp = os.path.join(model_dir, "vocabulary.txt")
    if not os.path.isfile(vp):
        return
    with open(vp, "r", encoding="utf-8", errors="surrogateescape") as f:
        lines = f.read().split("\n")
    changed = False
    while lines and _AI_HEADER_RE.match(lines[0].strip()):
        lines.pop(0)
        changed = True
    if changed:
        with open(vp, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
            f.write("\n".join(lines))


def load_model(model_dir: str, device: str = "cpu", compute_type: str = "int8"):
    sanitize_vocab(model_dir)
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # pragma: no cover
        raise RuntimeError("未安装 faster-whisper，请先执行: pip install faster-whisper") from e
    return WhisperModel(model_dir, device=device, compute_type=compute_type)


# --------------------------------------------------------------------------- #
# 音频处理
# --------------------------------------------------------------------------- #
def extract_audio(input_path: str, ffmpeg: str, out_wav: str) -> None:
    """用 ffmpeg 把任意媒体转成 16kHz 单声道 pcm_s16le 的 wav。"""
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", input_path,
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le", out_wav,
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0 or not os.path.isfile(out_wav):
        err = r.stderr.decode("utf-8", "replace")[-2000:]
        raise RuntimeError("ffmpeg 抽取音频失败:\n" + err)


def read_wav_as_float32(path: str):
    """用标准库 wave + numpy 读取 wav，绕过某些环境下 av 不可用的问题。"""
    import wave
    import numpy as np

    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())

    if sw == 2:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise RuntimeError(f"不支持的位深: {sw * 8}bit")
    if nch > 1:
        a = a.reshape(-1, nch).mean(axis=1)
    return np.ascontiguousarray(a, dtype=np.float32)


# --------------------------------------------------------------------------- #
# 转写主流程
# --------------------------------------------------------------------------- #
def run_transcribe(
    media: str,
    *,
    model_dir: str | None = None,
    size: str = DEFAULT_MODEL_SIZE,
    language: str = "zh",
    device: str = "cpu",
    compute_type: str = "int8",
    beam_size: int = 1,
    vad: bool = True,
    initial_prompt: str | None = None,
    on_segment=None,
    on_status=None,
):
    """返回 (segments, info)。segments 为 [{'start','end','text'}, ...]。"""
    if not os.path.isfile(media):
        raise FileNotFoundError(f"找不到文件: {media}")

    def st(msg: str) -> None:
        if on_status:
            try:
                on_status(msg)
            except Exception:
                _stderr(msg)
        else:
            _stderr(msg)

    md = resolve_model_dir(size, model_dir)
    st(f"模型目录: {md}")
    ffmpeg = find_ffmpeg()
    st(f"ffmpeg: {ffmpeg}")

    tmpdir = tempfile.mkdtemp(prefix="vt_")
    try:
        wav = os.path.join(tmpdir, "audio16k.wav")
        st("正在抽取音频…")
        extract_audio(media, ffmpeg, wav)
        st("正在读取音频…")
        audio = read_wav_as_float32(wav)
        st(f"音频时长 {len(audio) / SAMPLE_RATE:.1f}s，正在加载模型…")
        model = load_model(md, device, compute_type)
        st("开始转写…")

        gen, info = model.transcribe(
            audio,
            language=(None if language in ("auto", "", None) else language),
            beam_size=beam_size,
            vad_filter=vad,
            initial_prompt=initial_prompt,
        )

        segments = []
        for s in gen:
            item = {"start": round(float(s.start), 3), "end": round(float(s.end), 3), "text": s.text.strip()}
            if item["text"]:
                segments.append(item)
                if on_segment:
                    try:
                        on_segment(item)
                    except Exception:
                        pass
                else:
                    _stderr(f"[{item['start']:8.1f}] {item['text']}")
        return segments, info
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 输出格式化
# --------------------------------------------------------------------------- #
def _fmt_clock(sec: float, ms_sep: str = ",") -> str:
    if sec < 0:
        sec = 0
    total_ms = int(round(sec * 1000))
    h = total_ms // 3600000
    m = (total_ms % 3600000) // 60000
    s = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d}{ms_sep}{ms:03d}"


def _fmt_short(sec: float) -> str:
    total = int(sec)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _merge_paragraphs(segs, max_len: int = 120) -> str:
    out, cur = [], ""
    for s in segs:
        t = s["text"].strip()
        if not t:
            continue
        cur += t
        if len(cur) >= max_len or t[-1] in "。！？!?…":
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return "\n".join(out)


def format_output(segs, fmt: str = "txt") -> str:
    if fmt == "json":
        return json.dumps(segs, ensure_ascii=False, indent=2)
    if fmt == "srt":
        buf = []
        for i, s in enumerate(segs, 1):
            buf.append(str(i))
            buf.append(f"{_fmt_clock(s['start'])} --> {_fmt_clock(s['end'])}")
            buf.append(s["text"])
            buf.append("")
        return "\n".join(buf)
    if fmt == "vtt":
        buf = ["WEBVTT", ""]
        for i, s in enumerate(segs, 1):
            buf.append(str(i))
            buf.append(f"{_fmt_clock(s['start'], '.')} --> {_fmt_clock(s['end'], '.')}")
            buf.append(s["text"])
            buf.append("")
        return "\n".join(buf)
    if fmt == "ts":
        return "\n".join(f"[{_fmt_short(s['start'])}] {s['text']}" for s in segs)
    if fmt == "para":
        return _merge_paragraphs(segs)
    return "\n".join(s["text"] for s in segs)


def write_text(path: str, text: str) -> None:
    """写入文本并自愈去除被注入的 AI 头，保证产物干净。"""
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    text = strip_ai_header(text)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    # 再读回校验（防止写入后被再次注入）
    try:
        with open(path, "r", encoding="utf-8") as f:
            cur = f.read()
        fixed = strip_ai_header(cur)
        if fixed != cur:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(fixed)
    except Exception:
        pass


def default_output_path(input_path: str, fmt: str) -> str:
    base = os.path.splitext(input_path)[0]
    ext = {"srt": "srt", "vtt": "vtt", "json": "json"}.get(fmt, "txt")
    return base + "." + ext


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transcribe.py",
        description="视频/音频 -> 逐字稿（本地 faster-whisper，零 token 消耗）",
    )
    p.add_argument("input", help="媒体文件路径（视频或音频）")
    p.add_argument("-o", "--output", default=None, help="输出文件路径（默认与输入同目录同名）")
    p.add_argument(
        "-f", "--format", default="txt",
        choices=["txt", "para", "ts", "srt", "vtt", "json"],
        help="输出格式：txt=逐字稿分段(默认) para=逐字稿自然段 ts=带时间戳 srt/vtt=字幕 json=结构化",
    )
    p.add_argument("--timestamps", action="store_true", help="等价于 -f ts")
    p.add_argument("-l", "--language", default="zh", help="语言代码，默认 zh；auto=自动识别")
    p.add_argument("--model-size", default=DEFAULT_MODEL_SIZE,
                   help="模型尺寸 tiny/base/small/medium/large-v3，默认 small")
    p.add_argument("--model-dir", default=None, help="模型目录（优先级最高）")
    p.add_argument("--device", default="cpu", help="cpu 或 cuda")
    p.add_argument("--compute-type", default="int8", help="int8/int8_float16/float16/float32")
    p.add_argument("--beam-size", type=int, default=1, help="beam search 宽度，默认 1（快）")
    p.add_argument("--no-vad", action="store_true", help="关闭 VAD 静音过滤")
    p.add_argument("--initial-prompt", default=None, help="初始提示词，可引导术语/人名")
    return p


def main(argv=None) -> int:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    fmt = "ts" if args.timestamps else args.format

    if not os.path.isfile(args.input):
        _stderr(f"错误：找不到输入文件 {args.input}")
        return 2

    t0 = time.time()
    try:
        segs, info = run_transcribe(
            args.input,
            model_dir=args.model_dir,
            size=args.model_size,
            language=args.language,
            device=args.device,
            compute_type=args.compute_type,
            beam_size=args.beam_size,
            vad=not args.no_vad,
            initial_prompt=args.initial_prompt,
        )
    except Exception as e:
        _stderr(f"转写失败：{e}")
        return 1

    text = format_output(segs, fmt)
    out_path = args.output or default_output_path(args.input, fmt)
    write_text(out_path, text)

    lang = getattr(info, "language", "?")
    dur = getattr(info, "duration", 0) or 0
    _stderr("")
    _stderr(f"完成：{len(segs)} 段 / 音频 {dur:.1f}s / 语言 {lang} / 耗时 {time.time() - t0:.1f}s")
    _stderr(f"输出：{out_path}")
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())