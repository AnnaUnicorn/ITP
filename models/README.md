# 本地模型

本目录仅存放模型说明，权重不进入 Git。

U²-NetP ONNX 使用官方 rembg 发行版，约 4.7 MB，在 CPU 上完成去背景。安装器固定校验 MD5 `8e83ca70e441ab06c318d82300c84806`，与上游 manifest 一致；下载成功后输出 SHA-256 便于归档。服务启动和推理不会自动访问 GitHub 或 Hugging Face。

来源：[ONNX 发行](https://github.com/danielgatis/rembg/releases/tag/v0.0.0)、[上游校验定义](https://github.com/danielgatis/rembg/blob/main/rembg/sessions/u2netp.py)、[原模型 Apache-2.0 代码及模型说明](https://github.com/xuebinqin/U-2-Net)。分发前应复核代码与权重各自条款。

安装器 `scripts/download_models.py` 支持 `--url` 指定自行管理的国内镜像，固定校验不变；已经下载后可以将这一个权重文件复制到离线机器的相同路径。大型 3D 权重未下载。
