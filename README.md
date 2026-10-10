# 🎬 视频转写逐字稿工具（video-transcriber）

把视频 / 音频一键转成**逐字稿**——全程本地运行、离线可用、**不消耗任何云端 token**。
基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（Whisper 的高性能 CTranslate2 实现）。

## ✨ 特点

- 视频（mp4 / mkv / mov / avi / flv / wmv / webm / ts …）或音频（mp3 / m4a / wav / flac / ogg / opus …）→ 逐字稿
- 6 种输出：逐字稿分段 / 自然段 / 带时间戳 / SRT / VTT / JSON
- 四种用法：**简单桌面界面**、**网页界面**、**命令行**、**拖拽 bat**
- **免装 ffmpeg**：自动使用 `imageio-ffmpeg` 自带的 ffmpeg（装依赖即得），无需手动安装
- **可整体迁移**：整个文件夹拷到任何 Windows 电脑即可用（只需装 Python + 一键装依赖）
- **自动探测 Python**：不写死任何本机路径，换机后自动适配
- 自动清理环境注入的文件头，产物始终干净

## 🧳 换电脑迁移（重点）

本工具已做成「绿色便携」：**不含任何写死的本机路径**，整个文件夹复制即走。

迁移三步：

1. **拷贝**：把整个 `video-transcriber` 文件夹复制到新电脑
   （含模型，约 460 MB；若走 Git 仓库克隆则见下文「从 GitHub 克隆后」）。
2. **装 Python**：在新电脑安装 Python 3.9+（官网 <https://www.python.org/downloads/> ），
   安装向导里务必勾选 **Add python.exe to PATH**。
3. **装依赖**：双击文件夹里的 **`安装依赖.bat`**（需联网，一次性）。

之后双击 `启动简单UI.bat` 或 `启动UI.bat` 即可使用。

补充说明：

- **目标电脑不能联网**：先在有网的机器上执行
  `pip download -r requirements.txt -d wheels`，把 `wheels` 目录一起带走，
  再在目标机执行 `pip install --no-index --find-links wheels -r requirements.txt`。
- **想指定某个 Python 解释器**：把它的完整路径写入 `python_path.txt`（每行一个，`#` 为注释），
  或设置环境变量 `VIDEO_TRANSCRIBER_PY`。路径不存在时会被自动忽略并继续探测。
- 若双击 `.bat` 被系统提示「Internet 安全设置阻止打开文件」：右键该文件 →「属性」→
  勾选底部「解除锁定」；或参阅「常见问题」一节。

## 📦 从 GitHub 克隆后使用（重要）

本仓库**只含代码**——模型 `model.bin`（约 480 MB）超过 GitHub 单文件上限，未入库。克隆后补两步：

**双击 `一键启动.bat` 即可** —— 自动完成「检测 Python → 装依赖 → 下载模型 → 打开界面」，首次联网约几分钟。

也可分步操作：`安装依赖.bat` → `下载模型.bat` → `启动简单UI.bat`。

> 手动下载：模型来自魔搭 <https://modelscope.cn/models/pengzhendong/faster-whisper-small>，
> 把 `model.bin` 放到 `models/small/` 即可。
## 目录结构

```
video-transcriber/
├─ transcribe.py        核心引擎 + 命令行入口
├─ ui_simple.py         简单桌面界面（tkinter，单窗口）
├─ 启动简单UI.bat       双击启动简单界面
├─ app_web.py           本地网页界面（http.server）
├─ 启动UI.bat           双击启动网页界面
├─ 拖拽转写.bat         把文件拖到图标上直接转写
├─ 安装依赖.bat         一键安装 / 更新依赖（新电脑首次使用）
├─ _find_python.bat     公共脚本：自动探测可用的 Python 解释器
├─ python_path.txt      （可选）手动指定解释器
├─ requirements.txt     依赖清单
├─ models/
│   ├─ small/           模型目录（含 config / tokenizer / vocabulary）
│   └─ README.txt       模型说明（model.bin 需另行下载）
├─ 一键启动.bat         一键启动（装依赖 + 下模型 + 开界面）
├─ 下载模型.bat         单独下载模型 model.bin（约 480 MB）
└─ README.md
```

## 🚀 一键启动（最省事，推荐）

**双击 `一键启动.bat`** —— 自动完成「检测 Python → 装依赖 → 下载模型 → 打开界面」。
首次需联网、约几分钟；之后每次双击即直接开界面。

> 遇到问题可改用下面「快速开始」的分步方式逐一排查。

## 快速开始

### 1) 安装依赖（一次性）

新电脑请双击 **`安装依赖.bat`**；也可手动执行：

```
pip install -r requirements.txt
```

> 若机器已装 `faster-whisper` / `imageio-ffmpeg` / `numpy` 可跳过。

### 2) 简单桌面界面（最省事）

双击 **`启动简单UI.bat`** → 弹出单窗口 → 「选择文件…」→「开始转写」→
窗口实时显示逐字稿 → 「保存为 TXT…」或「复制全部」。

- 无需浏览器、无需命令行，一个窗口搞定。
- 界面本身只用 Python 标准库 `tkinter`，需要**带 tkinter 的 Python**（官方安装包默认自带）；
  `启动简单UI.bat` 会自动挑一个带 tkinter 的解释器来跑界面。
- 转写仍由引擎 `transcribe.py` 完成，界面会自动挑一个**装了 faster-whisper 的解释器**
  以子进程方式调用——你无需关心用哪个 Python。

### 3) 网页界面（网页端功能最全）

双击 **`启动UI.bat`** → 浏览器自动打开 → 填文件路径或上传 → 选格式 → 点「开始转写」。
结果可在线预览、复制全文或下载。可选格式最全（含 SRT / VTT / JSON）。

手动启动（自定义端口）：

```
python app_web.py --port 8765
```

### 4) 命令行

```
python transcribe.py D:\video.mp4
python transcribe.py D:\video.mp4 --timestamps
python transcribe.py D:\video.mp4 -f srt -o out.srt
python transcribe.py D:\audio.m4a -f json
```

### 5) 拖拽

把视频 / 音频文件直接拖到 **`拖拽转写.bat`** 图标上即可，逐字稿与源文件同目录
（同名 `.txt`，带时间戳）。

## 命令行参数

| 参数 | 说明 |
| --- | --- |
| `input` | 媒体文件路径（必填） |
| `-o, --output` | 输出文件路径（默认与输入同目录同名） |
| `-f, --format` | `txt` / `para` / `ts` / `srt` / `vtt` / `json`，默认 `txt` |
| `--timestamps` | 等价于 `-f ts`（逐字稿 + 时间戳） |
| `-l, --language` | 语言代码，默认 `zh`；`auto`=自动识别 |
| `--model-size` | `tiny` / `base` / `small` / `medium` / `large-v3`，默认 `small` |
| `--model-dir` | 指定模型目录（优先级最高） |
| `--device` | `cpu` / `cuda`，默认 `cpu` |
| `--compute-type` | `int8` / `int8_float16` / `float16` / `float32`，默认 `int8` |
| `--beam-size` | beam search 宽度，默认 `1`（最快） |
| `--no-vad` | 关闭 VAD 静音过滤 |
| `--initial-prompt` | 初始提示词，可引导术语、人名 |

## 输出格式

| 格式 | 内容 |
| --- | --- |
| `txt` | 逐字稿，一句一行 |
| `para` | 逐字稿，合并成自然段 |
| `ts` | 逐字稿 + `[mm:ss]` 时间戳 |
| `srt` / `vtt` | 字幕文件（可直接导入播放器 / 剪辑软件） |
| `json` | `[{"start":0.0,"end":1.2,"text":"…"}, …]` |

## 性能参考

本机实测（CPU，`int8`，`small` 模型）：**1 分钟音频 ≈ 14 秒转写**。
要更准可换 `medium`；要更快可换 `base` / `tiny`。

## 常见问题

- **要联网吗？** 不需要（仅首次装依赖需联网）。模型与 ffmpeg 都在本地。
- **消耗 token / 花钱吗？** 不。转写全部在本地 CPU 完成，0 成本。
- **换电脑要改什么吗？** 不用改代码。拷文件夹 → 装 Python → 双击 `安装依赖.bat` 即可（详见上文迁移章节）。
- **简单界面打不开？** 该界面需要 `tkinter`，请确认新电脑装的是官方 Python（默认自带 tkinter）；
  启动脚本会自动寻找带 tkinter 的解释器。
- **报错找不到 ffmpeg？** 正常情况下不会——装依赖时已包含 `imageio-ffmpeg`（自带 ffmpeg）；
  若被误删，执行 `pip install imageio-ffmpeg` 亦可。
- **模型放哪？** 放在 `models/<尺寸>/`，详见 `models/README.txt`；也可用 `--model-dir` 指定。
- **双击 .bat 提示「Internet 安全设置阻止打开文件」？** 右键该 `.bat` →「属性」→ 勾选「解除锁定」→ 确定。
  若仍被拦：控制面板 →「Internet 选项」→「安全」→「Internet」→「自定义级别」→
  把「加载应用程序和不安全文件」设为「提示」。
- **首次运行慢？** 首次要加载模型（数百 MB），之后会快。

## 环境要求

- 引擎：Python 3.9+，`faster-whisper`、`numpy`（`imageio-ffmpeg` 提供 ffmpeg）
- 简单桌面界面：需带 `tkinter` 的 Python（Windows 官方版默认包含）
- 模型文件：`small`（放在 `models/small/`，用「下载模型.bat」获取 model.bin）