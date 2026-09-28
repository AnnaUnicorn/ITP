# 本地 REST API

本地默认地址 `http://127.0.0.1:8000`，交互式 OpenAPI 文档在 `/docs`。仅适用于本机单用户；未提供公网身份认证。浏览器跨站写请求拒绝，Host 仅允许回环名称。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/health | 服务健康/version |
| GET | /api/capabilities | 配置是否齐全、分割权重是否存在；从不包含密钥 |
| POST | /api/assets?remove_background=false | multipart `file` 上传；返回 id/url/width/height/size |
| GET | /api/assets/{id} | 资产元数据 |
| GET | /api/assets/{id}/file | 预览文件；`?download=true` 返回附件 |
| POST | /api/jobs | JSON JobRequest；201 或未配置 503 |
| GET | /api/jobs | 最新 100 个任务 |
| GET | /api/jobs/{id} | 单个任务、阶段 ID、产物列表 |
| POST | /api/jobs/{id}/review | JSON `{"approve": true}` 确认姿势；false 放弃 |

上传需包含 Content-Length；上限约 10 MiB 加 multipart 开销。图片再经实际读取长度与解码验证。无图像资产或资产类型错误返回 422。任务输入禁止任意公网 URL，由本地已上传资产 ID 引用。

JobRequest 的完整模式以 OpenAPI 为准。主要参数为 front、views、pose_mode、pose_reference、face_count、topology、polygon_type、face_level、texture、texture_size、rig、neutral_pose_confirmed、export_fbx、seed。多视角与修改姿势互斥；custom 与 rig 互斥。

响应状态码：404 为不存在，409 为审核状态不匹配，413 为过大，422 为输入无效，503 为所需服务或本地权重未配置。云端执行错误写入任务 state=failed，不把供应商返回的敏感正文暴露出来。
