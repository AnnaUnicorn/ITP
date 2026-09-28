# 技术调研与来源

核验日期：2026-09-28。API、配额、价格和许可可能变化，真实接入时以账号控制台和最新官方条款为准。

## 视频目标

YouTube oEmbed 已返回视频标题和作者 MeshyAI。官方同名教程确认操作是“角色图片 + Custom Pose 姿势参考图片 → 3D”。未取得视频逐帧内容，不能声称已经视觉比对。

- [原视频](https://www.youtube.com/watch?v=r-413N5n0i8)
- [Meshy 同名教程与描述](https://www.meshy.ai/tutorials/custom-pose-generate-3d-characters-from-images-in-any-pose)
- [Meshy 当前姿势产品说明](https://www.meshy.ai/features/custom-pose)
- [Meshy 姿势操作文档](https://help.meshy.ai/en/articles/10255659-how-to-generate-3d-models-with-a-pose-t-pose-or-custom-poses)

视频与当前页面的操作有版本差异：视频描述上传参考图，当前产品页面另有逐关节控制。首版实现参考图路线；逐关节编辑没有被当作已经实现。

## 国内替代

| 原始模块 | 首版选择 | 限制 |
| --- | --- | --- |
| Meshy Pose | Qwen Image Edit Plus（国内百炼） | 图像级姿势变换，身份和姿势保真需验证 |
| Meshy 7/7.1 | Tencent AI3D Pro（3.1） | 托管推理，不可拆出内部 Image Encoder |
| Meshy T2 | SubmitReduceFaceJob | 云端智能拓扑，面数档位/面类型 |
| PBR | SubmitTextureTo3DJob | 纹理 UV 需与最终网格对应 |
| Rig | SubmitAutoRiggingJob | 人形角色需要规整 A/T 姿态 |
| 去背景 | U²-NetP ONNX（约 4.7 MB） | CPU 可运行；精细发丝/遮挡边界能力有限 |

- [腾讯国内 API 概览](https://cloud.tencent.cn/document/product/1804/120838)
- [官方 Python SDK 协议](https://github.com/TencentCloud/tencentcloud-sdk-python/blob/master/tencentcloud/ai3d/v20250513/models.py)
- [拓扑输入协议](https://cloud.tencent.cn/document/product/1804/126293)
- [纹理输入协议](https://cloud.tencent.com/document/product/1804/126292)
- [绑骨输入与姿态要求](https://cloud.tencent.com/document/product/1804/131618)
- [返回文件与多视图结构](https://cloud.tencent.com/document/api/1804/120828)
- [千问多图编辑输入、Base64、图像顺序](https://help.aliyun.com/zh/model-studio/qwen-image-edit-guide)
- [千问 API 协议](https://help.aliyun.com/zh/model-studio/qwen-image-edit-api)
- [U²-Net 原作者仓库](https://github.com/xuebinqin/U-2-Net)
- [U²-NetP ONNX 发行与校验](https://github.com/danielgatis/rembg/blob/main/rembg/sessions/u2netp.py)

## 本地 3D 模型评估

[Hunyuan3D-2.1 官方仓库](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) 提供几何和 PBR 路线，但需要 GPU 与大型权重/依赖，非“小模型”。当前主机没有检测到 NVIDIA 驱动，暂不下载安装整套模型。其许可与普通 MIT/Apache 不同，应单独核对权重条款。本版本只实际下载轻量分割模型。

## 证据边界

官方接口存在 ≠ 当前账号有权限；集成测试通过 ≠ 云端模型质量已验收；本机联网成功 ≠ 中国大陆每个网络均可达。运行阶段以国内 API 与本地资源为设计约束，安装阶段的开源依赖可以使用国内包镜像。正式模型调用产生的费用以账号控制台为准，不写死价格。
