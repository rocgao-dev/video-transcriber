# 模型目录说明

把 faster-whisper（CTranslate2 格式）模型放在这里，例如：

    models/
      small/
        config.json
        model.bin          （约 480 MB）
        tokenizer.json
        vocabulary.txt

工具会自动按 `models/<尺寸>/` 查找；也可用 --model-dir 指定任意目录。
模型随工具目录一起拷贝，换电脑无需重新下载。

## 支持的尺寸（越大越准、越慢）

    tiny  base  small  medium  large-v3

## 如何获取模型

方式一（推荐，离线可用）：把已有的 faster-whisper 模型目录整体复制进来。

方式二：用 Python 自动下载（需要联网）：

    from faster_whisper import WhisperModel
    WhisperModel("small", device="cpu", compute_type="int8",
                 download_root=r"<本工具目录>\models")

下载完成后，模型会出现在 models\small（或
models\models--Systran--faster-whisper-small\snapshots\...），
把它整理成 models/small/ 即可。

方式三：国内网络可用魔搭（ModelScope）仓库 pengzhendong/faster-whisper-small 下载同名文件。