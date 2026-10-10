# -*- coding: utf-8 -*-
"""视频转写逐字稿 —— 本地网页界面（零 token 消耗）。

用法:
    python app_web.py                     # 默认 127.0.0.1:8765
    python app_web.py --port 9000
    python app_web.py --no-browser
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 无论以何种方式启动，都保证能导入同目录的 transcribe 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcribe as engine  # noqa: E402

JOBS = {}
LOCK = threading.Lock()
TMP_DIR = tempfile.mkdtemp(prefix="vt_web_")


def _log(job, msg):
    with LOCK:
        job["logs"].append(msg)
        if len(job["logs"]) > 3000:
            del job["logs"][:1000]


def start_job(media, params):
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "state": "running", "logs": [], "result": None, "error": None,
           "out_path": None, "media": media, "seg_count": 0, "t0": time.time()}
    with LOCK:
        JOBS[jid] = job
    threading.Thread(target=_run_job, args=(jid, media, params), daemon=True).start()
    return jid


def _run_job(jid, media, params):
    job = JOBS[jid]

    def on_status(m):
        _log(job, m)

    def on_segment(item):
        _log(job, "[{:8.1f}] {}".format(item["start"], item["text"]))

    try:
        segs, info = engine.run_transcribe(
            media,
            model_dir=params.get("model_dir"),
            size=params.get("model_size", engine.DEFAULT_MODEL_SIZE),
            language=params.get("language", "zh"),
            device=params.get("device", "cpu"),
            compute_type=params.get("compute_type", "int8"),
            beam_size=int(params.get("beam_size", 1)),
            vad=params.get("vad", True),
            initial_prompt=params.get("initial_prompt"),
            on_segment=on_segment,
            on_status=on_status,
        )
        fmt = params.get("fmt", "txt")
        text = engine.format_output(segs, fmt)
        out = params.get("output") or engine.default_output_path(media, fmt)
        engine.write_text(out, text)
        with LOCK:
            job["result"] = text
            job["out_path"] = out
            job["seg_count"] = len(segs)
            job["state"] = "done"
            job["elapsed"] = time.time() - job["t0"]
        _log(job, "完成：{} 段，输出 {}".format(len(segs), out))
    except Exception as e:  # noqa: BLE001
        with LOCK:
            job["error"] = str(e)
            job["state"] = "error"
        _log(job, "错误：" + str(e))


def _parse_multipart(body: bytes, boundary: bytes):
    fields, files = {}, {}
    delim = b"--" + boundary
    for part in body.split(delim):
        part = part.strip(b"\r\n")
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        head_txt = head.decode("utf-8", "replace")
        m = re.search(r'name="([^"]*)"', head_txt)
        if not m:
            continue
        name = m.group(1)
        fn = re.search(r'filename="([^"]*)"', head_txt)
        if fn and fn.group(1):
            files[name] = (fn.group(1), data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoTranscriber/1.0"

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, text, code=200, ctype="text/plain; charset=utf-8"):
        data = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            self._send_text(HTML_PAGE, ctype="text/html; charset=utf-8")
            return
        if u.path == "/health":
            self._send_json({"ok": True})
            return
        if u.path == "/status":
            jid = (qs.get("id") or [""])[0]
            job = JOBS.get(jid)
            if not job:
                self._send_json({"error": "unknown job"}, 404)
                return
            with LOCK:
                self._send_json({
                    "state": job["state"],
                    "logs": job["logs"][-800:],
                    "error": job["error"],
                    "seg_count": job["seg_count"],
                    "out_path": job["out_path"],
                    "elapsed": job.get("elapsed", time.time() - job["t0"]),
                    "has_result": job["result"] is not None,
                })
            return
        if u.path == "/result":
            jid = (qs.get("id") or [""])[0]
            job = JOBS.get(jid)
            if not job or job["result"] is None:
                self._send_text("no result", 404)
                return
            self._send_text(job["result"])
            return
        if u.path == "/download":
            jid = (qs.get("id") or [""])[0]
            job = JOBS.get(jid)
            if not job or not job["out_path"] or not os.path.isfile(job["out_path"]):
                self._send_text("no file", 404)
                return
            fn = os.path.basename(job["out_path"])
            data = open(job["out_path"], "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % fn)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_text("not found", 404)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/start":
            self._send_text("not found", 404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        ctype = self.headers.get("Content-Type", "")
        body = self.rfile.read(length) if length else b""

        fields, files = {}, {}
        if "multipart/form-data" in ctype:
            m = re.search(r'boundary=("?)([^";]+)\1', ctype)
            if m:
                fields, files = _parse_multipart(body, m.group(2).encode())
        else:
            fields = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}

        media = (fields.get("path") or "").strip().strip('"').strip("'")
        if "file" in files and files["file"][1]:
            fn, data = files["file"]
            safe = os.path.basename(fn) or "upload.bin"
            media = os.path.join(TMP_DIR, uuid.uuid4().hex[:8] + "_" + safe)
            with open(media, "wb") as f:
                f.write(data)

        if not media or not os.path.isfile(media):
            self._send_json({"error": "请填写有效的文件路径，或上传文件"}, 400)
            return

        fmt = fields.get("format", "txt")
        if fields.get("timestamps") in ("1", "true", "on"):
            fmt = "ts"
        params = {
            "fmt": fmt,
            "model_size": fields.get("model_size", engine.DEFAULT_MODEL_SIZE),
            "language": fields.get("language", "zh"),
            "model_dir": fields.get("model_dir") or None,
            "vad": not (fields.get("no_vad") in ("1", "true", "on")),
        }
        jid = start_job(media, params)
        self._send_json({"job_id": jid, "media": media})


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>视频转写逐字稿</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;font-family:"Microsoft YaHei",system-ui,-apple-system,Segoe UI,sans-serif;
       background:linear-gradient(160deg,#0f172a,#1e293b);color:#e2e8f0;min-height:100vh}
  .wrap{max-width:880px;margin:0 auto;padding:32px 20px 60px}
  h1{margin:0 0 6px;font-size:26px}
  .sub{margin:0 0 22px;color:#94a3b8;font-size:13px}
  .card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09);
        border-radius:14px;padding:20px;margin-bottom:18px}
  label{display:block;font-size:13px;color:#cbd5e1;margin:0 0 6px}
  input[type=text]{width:100%;padding:11px 12px;border-radius:9px;border:1px solid #334155;
        background:#0b1220;color:#e2e8f0;font-size:14px}
  input[type=file]{font-size:13px;color:#94a3b8}
  .row{display:flex;gap:14px;flex-wrap:wrap;margin-top:14px}
  .row>div{flex:1;min-width:160px}
  select{width:100%;padding:10px 12px;border-radius:9px;border:1px solid #334155;
        background:#0b1220;color:#e2e8f0;font-size:14px}
  .chk{display:flex;align-items:center;gap:8px;margin-top:14px;color:#cbd5e1;font-size:13px}
  button{cursor:pointer;border:0;border-radius:10px;font-size:15px;padding:12px 22px;font-weight:600}
  #go{margin-top:18px;width:100%;background:linear-gradient(90deg,#2563eb,#7c3aed);color:#fff}
  #go:disabled{opacity:.55;cursor:not-allowed}
  .bar{display:flex;justify-content:space-between;font-size:14px;color:#93c5fd;margin-bottom:10px}
  pre{background:#0b1220;border:1px solid #1e293b;border-radius:10px;padding:14px;
      max-height:420px;overflow:auto;white-space:pre-wrap;word-break:break-word;
      font-size:13px;line-height:1.7;margin:0}
  #actions{margin-top:14px;display:flex;gap:12px}
  .btn{display:inline-block;text-decoration:none;background:#2563eb;color:#fff;padding:11px 20px;
       border-radius:10px;font-size:14px;font-weight:600}
  .btn.ghost{background:transparent;border:1px solid #334155;color:#cbd5e1}
  .hint{color:#64748b;font-size:12px;margin-top:8px}
</style>
</head>
<body>
<div class="wrap">
  <h1>🎬 视频转写逐字稿</h1>
  <p class="sub">本地 faster-whisper 引擎 · 全程离线 · 不消耗云端 token</p>

  <div class="card">
    <label>媒体文件路径（推荐）</label>
    <input type="text" id="path" placeholder="例如 D:\video.mp4 或 C:\Users\...\VID_1024.mp4">
    <div class="row">
      <div>
        <label>或上传文件（大文件较慢）</label>
        <input type="file" id="file">
      </div>
    </div>
    <div class="row">
      <div>
        <label>输出格式</label>
        <select id="format">
          <option value="txt">txt · 逐字稿（分段）</option>
          <option value="para">para · 逐字稿（自然段）</option>
          <option value="ts">ts · 逐字稿 + 时间戳</option>
          <option value="srt">srt · 字幕</option>
          <option value="vtt">vtt · 网页字幕</option>
          <option value="json">json · 结构化</option>
        </select>
      </div>
      <div>
        <label>语言</label>
        <select id="language">
          <option value="zh">中文</option>
          <option value="en">英文</option>
          <option value="auto">自动识别</option>
        </select>
      </div>
      <div>
        <label>模型</label>
        <select id="model_size">
          <option value="small">small（推荐）</option>
          <option value="base">base（更快）</option>
          <option value="medium">medium（更准，慢）</option>
        </select>
      </div>
    </div>
    <label class="chk"><input type="checkbox" id="no_vad"> 关闭静音过滤（VAD，一般不需要）</label>
    <button id="go">开始转写</button>
    <div class="hint">首次加载模型需数秒；1 分钟音频约需 10~30 秒（CPU）。</div>
  </div>

  <div class="card" id="panel" style="display:none">
    <div class="bar"><span id="state">…</span><span id="timer"></span></div>
    <pre id="log"></pre>
    <div id="actions" style="display:none">
      <a id="dl" class="btn" href="#">⬇ 下载结果</a>
      <button id="copy" class="btn ghost">复制全文</button>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let timer = null;

$('go').onclick = async () => {
  const fd = new FormData();
  fd.append('path', $('path').value.trim());
  if ($('file').files[0]) fd.append('file', $('file').files[0]);
  fd.append('format', $('format').value);
  fd.append('language', $('language').value);
  fd.append('model_size', $('model_size').value);
  if ($('no_vad').checked) fd.append('no_vad', '1');

  $('panel').style.display = 'block';
  $('log').textContent = '';
  $('actions').style.display = 'none';
  $('state').textContent = '提交中…';
  $('go').disabled = true;

  let j;
  try {
    const r = await fetch('/start', {method:'POST', body: fd});
    j = await r.json();
  } catch (e) { $('state').textContent = '请求失败：' + e; $('go').disabled = false; return; }

  if (j.error) { $('state').textContent = '❌ ' + j.error; $('go').disabled = false; return; }

  const t0 = Date.now();
  clearInterval(timer);
  timer = setInterval(() => { $('timer').textContent = ((Date.now()-t0)/1000).toFixed(0) + ' s'; }, 200);
  poll(j.job_id);
};

async function poll(id) {
  let j;
  try { j = await (await fetch('/status?id=' + id)).json(); }
  catch (e) { setTimeout(() => poll(id), 1200); return; }

  $('log').textContent = (j.logs || []).join('\n');
  $('log').scrollTop = $('log').scrollHeight;

  if (j.state === 'done') {
    clearInterval(timer);
    $('state').textContent = '✅ 完成 · ' + (j.seg_count || 0) + ' 段';
    $('dl').href = '/download?id=' + id;
    $('dl').setAttribute('download', (j.out_path || 'transcript.txt').split(/[\\/]/).pop());
    $('actions').style.display = 'flex';
    $('log').dataset.id = id;
    $('go').disabled = false;
  } else if (j.state === 'error') {
    clearInterval(timer);
    $('state').textContent = '❌ ' + j.error;
    $('go').disabled = false;
  } else {
    $('state').textContent = '转写中…';
    setTimeout(() => poll(id), 1000);
  }
}

$('copy').onclick = async () => {
  const id = $('log').dataset.id;
  const t = await (await fetch('/result?id=' + id)).text();
  try { await navigator.clipboard.writeText(t); } catch (e) {}
  $('copy').textContent = '已复制 ✓';
  setTimeout(() => $('copy').textContent = '复制全文', 1500);
};
</script>
</body>
</html>
"""


def make_server(port: int):
    for p in range(port, port + 60):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), Handler), p
        except OSError:
            continue
    raise SystemExit("找不到可用端口（8765 起 60 个端口均被占用）")


def main(argv=None) -> int:
    try:
        sys_stderr = __import__("sys").stderr
        sys_stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="视频转写逐字稿 - 本地网页界面")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)

    srv, port = make_server(a.port)
    url = "http://127.0.0.1:%d/" % port
    print("视频转写工具已启动：%s" % url, flush=True)
    print("在浏览器打开上面的地址；按 Ctrl+C 停止。", flush=True)
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())