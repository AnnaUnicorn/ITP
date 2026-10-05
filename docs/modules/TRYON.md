# 虚拟试穿

独立侧栏页面，不修改原人体建模入口。人物与服装各上传 1–6 张图，视角仅限正、背、左、右、左前、右前，至少各一张；先经 `/api/assets` 保存为本地资产，`POST /api/tryons` 创建独立任务。未提供的视角选取方位角最接近的已上传参考图引导生成；输入越少，身份和服装一致性越难保证。旧版 `consistent_confirmed` 字段可兼容接收，但不作为创建前置条件。API Key 留空直到用户在设置页填写，只在本地 `.env` 保存，不向页面回传。

任务按正面、背面、左侧、右侧、左前、右前顺序生成。正面使用两张原图；其余视角各使用人物与服装当前或回退视角、两张补充参考与已生成正面，共五张参考图。提示词约束人物身份、脸部、体型、姿势、服装版型与色彩，但生成式模型不提供严格的一致性保证；结果需人工检查。每张完成后转为本地 PNG 资产，逐张显示与下载。调用状态持久化；如调用中进程中断，不自动重提付费请求，以免重复计费。

可选 `seedream`、`flux`、`flux_max`、`flux_klein`、`flux_klein_9b`、`gpt_image` 六种 `provider`。`GET /api/capabilities` 的 `tryon_providers` 返回各自是否已配置。SeedDream 使用北京方舟；FLUX 使用 BFL 异步接口（Pro 为 `/v1/flux-2-pro`，Max 为 `/v1/flux-2-max`）、轮询 `/v1/get_result` 并下载结果；GPT Image 2 使用兼容 OpenAI `/v1/images/edits` 的多图 JSON 请求与 base64 结果。FLUX 和 GPT 可填写从本机可访问的兼容 HTTPS 地址，官方站点在中国大陆的直连可用性不作保证。FLUX 模型由接口路径选定，`flux_model` 和 `flux_max_model` 仅用于任务记录；GPT 模型 ID 进入请求体。服务调用失败不自动切换其他服务。

## FLUX.2 Max API

在生图模型下拉框选择 `FLUX.2 Max`（`provider=flux_max`）。设置页有独立的服务地址、模型标识和 API Key；默认地址和 Key 为空，不复制 Pro 或 Klein 的密钥，不下载本地权重。模型标识默认为 `flux-2-max`。配置保存后立即生效，未配置时禁止提交试穿任务，但不影响原人体建模。

配置项为 `ITP_FLUX_MAX_ENDPOINT`、`ITP_FLUX_MAX_MODEL`、`ITP_FLUX_MAX_API_KEY`。官方地址是 `https://api.bfl.ai/v1/flux-2-max`；也可填写可访问的 **BFL 协议兼容 HTTPS 服务**，路径必须为 `/v1/flux-2-max`，不能直接填写 OpenAI 风格接口。使用 `x-key` 鉴权，图片字段为 `input_image`、`input_image_2` 至 `input_image_8`（JPEG base64，最多八张）；提交返回任务 `id` 和 `polling_url`，就绪时下载 `result.sample`。轮询地址必须属于所配置服务的同一主机 `/v1/get_result`，密钥不会附带到结果图片下载请求。

Max 沿用当前六视图生成顺序和人物/服装/正面结果参考策略，最终生成六张本地图片，可继续原有 3D 流程。本次仅进行了协议单元测试，不调用收费 API；“已配置”不代表账号权限、余额或实际生图质量已验证。

### 海鲸配置接入状态

Pro 与 Max 均接受并保存 `https://api.haijingai.com/v2/images/generations`，使用各自独立的模型与密钥配置，不再因 BFL 路径限制拒绝保存。公网设置页允许通过网站 Basic 登录认证的用户保存配置；参见 [部署权限说明](../../deploy/autodl/README.md)。

**海鲸多参考图换装尚未完成适配。** [模型页面](https://api.haijingai.com/api-docs/model-detail/flux-2-max/)列出了参考图计费，但 [公开 API 文档](https://api.haijingai.com/api-docs/api/image-generation/)和在线体验请求只说明 `model`、`prompt`、`aspect_ratio` 等文字生成参数，没有给出上传参考图片的字段或格式。不能据此断言服务不支持图生图，也不能凭空把 `images` / `input_image` 当作已验证字段。

因此当前 `tryon_provider_issues` 会明确提示传图协议待确认，页面禁用试穿提交，API 在创建任务前返回说明，直调适配器也不会发送付费请求。现有 BFL、Klein、SeedDream、GPT 和独立人体建模不受影响。获得海鲸包含人物与服装参考图的真实请求示例后，才可完成 Bearer、多参考图上传、URL/Base64 结果的完整适配。本次没有调用海鲸生成 API。

FLUX.2 Klein 4B 是自建服务，代码见 `services/flux_klein/`。ITP 的 `flux_klein` 适配器通过带 Bearer Token 的 `POST /v1/flux-klein/edit` 发送 1–4 张 JPEG data URL、提示词与模型标识，接收 PNG base64；正面最多两张参考图，其他视角最多四张，优先保留当前人物、当前服装与已生成的正面换装图。`GET /api/tryon-providers/flux-klein/health` 检查远端模型是否实际加载；未就绪时不会创建任务。配置项：`ITP_FLUX_KLEIN_ENDPOINT`、`ITP_FLUX_KLEIN_API_KEY`、`ITP_FLUX_KLEIN_MODEL`。用户在右侧服务卡片的下拉框选择模型；窄屏的选择框位于左侧设置区。

FLUX.2 Klein 9B 使用独立的 `flux_klein_9b` 选项，配置为 `ITP_FLUX_KLEIN_9B_ENDPOINT`、`ITP_FLUX_KLEIN_9B_API_KEY`、`ITP_FLUX_KLEIN_9B_MODEL`（默认 `flux.2-klein-9b`）。它与 4B 采用相同的图片协议和四参考图策略，六张输出可直接继续生成 3D。`GET /api/tryon-providers/flux-klein-9b/health` 会同时检查就绪状态和模型标识；把 9B 地址误填为 4B 服务时会拒绝创建任务。两种服务配置与访问令牌互相独立。自建服务如何加载对应权重见 [FLUX 服务文档](../../services/flux_klein/README.md)。

`GET /api/tryons/{id}` 查询进度；`POST /api/tryons/{id}/continue` 仅在六张完成后创建原有 3D 任务，直接复用六个本地资产 ID，不重复上传。若不继续，图片仍可保存。接口未配置时试穿不可提交，但原有 `/api/jobs` 保持可用。

## 页面布局

试穿页面沿用人体建模工作台的视觉结构：左侧是任务名称、人物和服装上传框；中间是深色主预览、流程状态和六张结果缩略图；右侧是模型下拉选择、所选服务状态和逐视角生成进度。上传框完整显示图片，并可放大查看；窄屏将上传区与预览区纵向排列，模型选择移至左侧设置区。结果生成后可切换主预览、逐张保存，或继续生成 3D 模型。页面代码位于 `frontend/src/TryOnPage.tsx`，试穿工作台样式位于 `frontend/src/TryOnWorkspace.css`。

接口依据：[火山引擎图片生成 API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh)、[BFL FLUX.2 API](https://github.com/black-forest-labs/skills/blob/master/skills/bfl-api/references/endpoints.md)、[FLUX.2 Klein 4B 模型卡](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)、[OpenAI 图像编辑 API](https://developers.openai.com/api/reference/resources/images/methods/edit)、[GPT Image 2 模型](https://developers.openai.com/api/docs/models/gpt-image-2)。
