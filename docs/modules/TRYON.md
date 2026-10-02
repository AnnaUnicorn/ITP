# 虚拟试穿

独立侧栏页面，不修改原人体建模入口。人物与服装各需上传正、背、左、右、左前、右前六张图；先经 `/api/assets` 保存为本地资产，`POST /api/tryons` 创建独立任务。页面不再要求单独勾选素材一致性，创建任务仍需两组完整六视图；旧版 `consistent_confirmed` 字段可兼容接收，但不作为创建前置条件。SeedDream 5.0 Flash 通过火山方舟北京节点调用，凭据留空直到用户在设置页填写。服务端配置字段为 `ITP_SEEDREAM_ENDPOINT`、`ITP_SEEDREAM_API_KEY`、`ITP_SEEDREAM_MODEL`。API Key 只在本地 `.env` 保存，不向页面回传。

任务按正面、背面、左侧、右侧、左前、右前顺序生成。正面使用两张原图；其余视角各使用人物当前视图、衣服当前视图、两张正面原图与已生成正面，共五张参考图。提示词约束人物身份、脸部、体型、姿势、服装版型与色彩，但生成式模型不提供严格的一致性保证；结果需人工检查。每张完成后转为本地 PNG 资产，逐张显示与下载。调用状态持久化；如调用中进程中断，不自动重提付费请求，以免重复计费。

`GET /api/tryons/{id}` 查询进度；`POST /api/tryons/{id}/continue` 仅在六张完成后创建原有 3D 任务，直接复用六个本地资产 ID，不重复上传。若不继续，图片仍可保存。接口未配置时试穿不可提交，但原有 `/api/jobs` 保持可用。

## 页面布局

试穿页面沿用人体建模工作台的视觉结构：左侧是任务名称、人物六视图和服装六视图；中间是深色主预览、流程状态和六张结果缩略图；右侧是服务连接情况和逐视角生成进度。窄屏将上传区与预览区纵向排列。结果生成后可切换主预览、逐张保存，或继续生成 3D 模型。页面代码位于 `frontend/src/TryOnPage.tsx`，试穿工作台样式位于 `frontend/src/TryOnWorkspace.css`。

接口依据：[火山引擎图片生成 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)、[SeedDream 5.0 模型指南](https://docs.volcengine.com/docs/ark/seedream-4-0-5-0?lang=zh)。
