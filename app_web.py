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
import queue
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
BATCHES = {}
JOB_QUEUE = queue.Queue()
LOCK = threading.Lock()
TMP_DIR = tempfile.mkdtemp(prefix="vt_web_")
_WORKER_STARTED = False


def _log(job, msg):
    with LOCK:
        job["logs"].append(msg)
        if len(job["logs"]) > 3000:
            del job["logs"][:1000]


def _ensure_worker():
    """启动唯一后台工作线程：多个文件按提交顺序依次转写，避免同时抢 CPU。"""
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True
    threading.Thread(target=_worker_loop, daemon=True).start()


def _worker_loop():
    while True:
        jid, media, params = JOB_QUEUE.get()
        try:
            _run_job(jid, media, params)
        finally:
            JOB_QUEUE.task_done()


def start_job(media, params, batch_id=None, name=None):
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "state": "queued", "logs": [], "result": None, "error": None,
           "out_path": None, "media": media, "seg_count": 0, "t0": time.time(),
           "batch": batch_id, "name": name or os.path.basename(media)}
    with LOCK:
        JOBS[jid] = job
    _ensure_worker()
    JOB_QUEUE.put((jid, media, params))
    return jid


def _run_job(jid, media, params):
    job = JOBS[jid]
    with LOCK:
        job["state"] = "running"
        job["t0"] = time.time()

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
    """解析 multipart。files 为列表，支持同一字段名出现多次（多文件上传）。"""
    fields, files = {}, []
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
            files.append({"name": name, "filename": fn.group(1), "data": data})
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
        if u.path == "/batch":
            bid = (qs.get("batch") or [""])[0]
            jids = BATCHES.get(bid)
            if not jids:
                self._send_json({"error": "unknown batch"}, 404)
                return
            out = []
            for jid in jids:
                job = JOBS.get(jid)
                if not job:
                    continue
                with LOCK:
                    out.append({
                        "id": jid,
                        "name": job.get("name") or os.path.basename(job.get("media") or ""),
                        "state": job["state"],
                        "logs": job["logs"][-800:],
                        "error": job["error"],
                        "seg_count": job["seg_count"],
                        "out_path": job["out_path"],
                        "elapsed": job.get("elapsed", time.time() - job["t0"]),
                        "has_result": job["result"] is not None,
                    })
            self._send_json({"batch": bid, "jobs": out})
            return
        if u.path == "/download_all":
            bid = (qs.get("batch") or [""])[0]
            jids = BATCHES.get(bid)
            if not jids:
                self._send_text("no batch", 404)
                return
            import io
            import zipfile
            buf = io.BytesIO()
            used, n = {}, 0
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for jid in jids:
                    job = JOBS.get(jid)
                    if not job or not job.get("out_path") or not os.path.isfile(job["out_path"]):
                        continue
                    p = job["out_path"]
                    base = os.path.basename(p)
                    if base in used:
                        used[base] += 1
                        root, ext = os.path.splitext(base)
                        base = "%s_%d%s" % (root, used[base], ext)
                    else:
                        used[base] = 0
                    z.write(p, arcname=base)
                    n += 1
            if n == 0:
                self._send_text("no file", 404)
                return
            data = buf.getvalue()
            fn = "transcripts_%s.zip" % bid[:8]
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
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

        fields, files = {}, []
        if "multipart/form-data" in ctype:
            m = re.search(r'boundary=("?)([^";]+)\1', ctype)
            if m:
                fields, files = _parse_multipart(body, m.group(2).encode())
        else:
            fields = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}

        # 收集待转写目标：路径（可多行，每行一个）+ 上传文件（可多个）
        items = []
        raw_paths = fields.get("paths") or fields.get("path") or ""
        for line in re.split(r"[\r\n]+", raw_paths):
            p = line.strip().strip('"').strip("'")
            if p:
                items.append((p, os.path.basename(p)))
        for f in files:
            if not f.get("data"):
                continue
            safe = os.path.basename(f["filename"]) or "upload.bin"
            media = os.path.join(TMP_DIR, uuid.uuid4().hex[:8] + "_" + safe)
            with open(media, "wb") as fh:
                fh.write(f["data"])
            items.append((media, safe))

        valid = [(m, n) for (m, n) in items if m and os.path.isfile(m)]
        if not valid:
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

        batch_id = uuid.uuid4().hex[:12]
        jobs, jids = [], []
        for (m, n) in valid:
            jid = start_job(m, params, batch_id=batch_id, name=n)
            jids.append(jid)
            jobs.append({"job_id": jid, "media": m, "name": n})
        BATCHES[batch_id] = jids
        self._send_json({"batch_id": batch_id, "jobs": jobs})


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
  textarea{width:100%;padding:11px 12px;border-radius:9px;border:1px solid #334155;
        background:#0b1220;color:#e2e8f0;font-size:14px;resize:vertical;font-family:inherit}
  .drop{margin-top:8px;border:1px dashed #334155;border-radius:9px;padding:12px;text-align:center;
        color:#64748b;font-size:12px}
  .drop.on{border-color:#7c3aed;color:#c4b5fd;background:rgba(124,58,237,.08)}
  .list{list-style:none;margin:0 0 10px;padding:0}
  .item{display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid #1e293b;
        border-radius:9px;background:#0b1220;margin-bottom:8px;font-size:13px}
  .item .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .item .st{color:#93c5fd;font-size:12px;white-space:nowrap}
  .item.done .st{color:#4ade80}
  .item.error .st{color:#f87171}
  .item.running .st{color:#fbbf24}
  .item a.mini{color:#60a5fa;text-decoration:none;font-size:12px;border:1px solid #334155;
        padding:3px 10px;border-radius:7px}
  .item a.mini:hover{background:#1e293b}
</style>
</head>
<body>
<div class="wrap">
  <h1>🎬 视频转写逐字稿</h1>
  <p class="sub">本地 faster-whisper 引擎 · 全程离线 · 不消耗云端 token</p>

  <div class="card">
    <label>媒体文件路径（可选，支持多个，每行一个）</label>
    <textarea id="paths" rows="3" placeholder="例如
D:\video.mp4
C:\Users\...\VID_1024.mp4"></textarea>
    <div class="row">
      <div>
        <label>或上传文件（可多选 / 可拖入，大文件较慢）</label>
        <input type="file" id="file" multiple>
        <div id="drop" class="drop">把文件拖到这里（可多个）</div>
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
    <div class="hint">可一次选择多个文件，将按顺序依次转写；首次加载模型需数秒，1 分钟音频约需 10~30 秒（CPU）。</div>
  </div>

  <div class="card" id="panel" style="display:none">
    <div class="bar"><span id="state">…</span><span id="timer"></span></div>
    <ul id="list" class="list"></ul>
    <div id="actions" style="display:none">
      <a id="dlall" class="btn" href="#">⬇ 全部下载 (zip)</a>
    </div>
    <pre id="log"></pre>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let timer = null;

// 拖拽放入文件选择框（支持多个）
const drop = $('drop');
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.add('on');
}));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.remove('on');
}));
drop.addEventListener('drop', e => {
  if (e.dataTransfer && e.dataTransfer.files.length) $('file').files = e.dataTransfer.files;
});

$('go').onclick = async () => {
  const fd = new FormData();
  const paths = $('paths').value.trim();
  if (paths) fd.append('paths', paths);
  const fl = $('file').files;
  for (let i = 0; i < fl.length; i++) fd.append('file', fl[i]);
  fd.append('format', $('format').value);
  fd.append('language', $('language').value);
  fd.append('model_size', $('model_size').value);
  if ($('no_vad').checked) fd.append('no_vad', '1');

  $('panel').style.display = 'block';
  if (!paths && !fl.length) { $('state').textContent = '请先填写文件路径或选择文件'; return; }

  $('list').innerHTML = '';
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
  $('state').textContent = '共 ' + j.jobs.length + ' 个文件，依次转写中…';
  pollBatch(j.batch_id, t0);
};

function render(items) {
  const ul = $('list');
  ul.innerHTML = '';
  items.forEach(it => {
    const li = document.createElement('li');
    li.className = 'item ' + it.state;
    let st = '排队中';
    if (it.state === 'running') st = '转写中…';
    else if (it.state === 'done') st = '✅ 完成 · ' + (it.seg_count || 0) + ' 段';
    else if (it.state === 'error') st = '❌ ' + (it.error || '失败');
    const nm = document.createElement('span');
    nm.className = 'nm'; nm.textContent = it.name;
    const stEl = document.createElement('span');
    stEl.className = 'st'; stEl.textContent = st;
    li.appendChild(nm); li.appendChild(stEl);
    if (it.state === 'done') {
      const a = document.createElement('a');
      a.className = 'mini'; a.href = '/download?id=' + it.id;
      a.setAttribute('download', (it.out_path || 'transcript.txt').split(/[\\/]/).pop());
      a.textContent = '下载'; li.appendChild(a);
    }
    ul.appendChild(li);
  });
}

async function pollBatch(bid, t0) {
  let d;
  try { d = await (await fetch('/batch?batch=' + bid)).json(); }
  catch (e) { setTimeout(() => pollBatch(bid, t0), 1200); return; }

  const items = d.jobs || [];
  render(items);

  const running = items.find(x => x.state === 'running')
                  || items.filter(x => x.state === 'done' || x.state === 'error').slice(-1)[0];
  if (running) {
    try {
      const s = await (await fetch('/status?id=' + running.id)).json();
      $('log').textContent = (s.logs || []).join('\n');
      $('log').scrollTop = $('log').scrollHeight;
    } catch (e) {}
  }

  const doneAll = items.length && items.every(x => x.state === 'done' || x.state === 'error');
  if (doneAll) {
    clearInterval(timer);
    const ok = items.filter(x => x.state === 'done').length;
    const bad = items.length - ok;
    $('state').textContent = '✅ 全部结束 · 成功 ' + ok + (bad ? (' / 失败 ' + bad) : '');
    if (ok) { $('dlall').href = '/download_all?batch=' + bid; $('actions').style.display = 'flex'; }
    $('go').disabled = false;
  } else {
    setTimeout(() => pollBatch(bid, t0), 1000);
  }
}
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