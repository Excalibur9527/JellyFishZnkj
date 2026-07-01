# 生成准备架构

## 定位

Jellyfish 当前已经将多条生成链逐步收敛到统一的“生成准备”模型，用于解决以下问题：

- 基础真值与最终提交内容混用
- 预览与提交使用的上下文不一致
- 页面内部状态散落，`stale / loading / submit` 语义混乱

当前已接入该架构的链路包括：

1. 分镜帧图片生成
2. 视频提示词预览与提交
3. 资产图片生成（角色 / 演员 / 场景 / 道具 / 服装）

## 统一模型

当前统一使用 4 层结构：

1. `Base Draft`
   - 可持久化、可编辑的业务真值
2. `Context`
   - 本次生成依赖的动态上下文
3. `Derived Preview`
   - 基于 `Base Draft + Context` 推导出的预览结果
4. `Submission Payload`
   - 最终提交给模型的运行载荷

## 后端当前结构

当前统一服务目录位于：

```text
backend/app/services/studio/generation/
├── shared/
├── frame/
├── video/
└── asset_image/
```

### `shared`

负责放置生成准备的共享类型：

- `GenerationBaseDraft`
- `GenerationContext`
- `GenerationDerivedPreview`
- `GenerationSubmissionPayload`

### `frame`

当前关键帧图片链已经按以下职责拆分：

- `build_base`
- `build_context`
- `derive_preview`
- `build_submission`

当前 API 仍保持原路径不变，但内部已经开始调用这一层服务。

### `video`

当前视频链已经开始使用同样的四段式结构：

- `build_base`
- `build_context`
- `derive_preview`
- `build_submission`

当前 `preview-prompt` 与 `create video task` 已共享同一份 `reference_mode + images` 上下文。
其中工作室当前使用的 `film/tasks/video/preview-prompt` 也会返回完整 `pack`：

- `previous_shot_summary`
- `next_shot_goal`
- `continuity_guidance`
- `composition_anchor`
- `screen_direction_guidance`
- `action_beats`
- `action_beat_phases`

因此工作室视频提示词预览与 studio 侧底层 pack 现在保持同源，不再出现“提示词有值但连续性上下文始终为空”的接口分叉。

当前视频参数已收口为以 `ratio` 为唯一业务主参数：

- 项目级默认：`Project.default_video_ratio`
- 分镜级覆盖：`ShotDetail.override_video_ratio`
- 前端在提交视频任务时显式传入本次生效的 `ratio`
- 后端直接使用请求中的 `ratio` 创建任务
- 若某个供应商不直接支持 `ratio`，由 provider adapter 在执行层内部派生辅助 `size`
- 前端比例枚举来自当前默认视频模型 capability 动态返回，不再使用静态常量
- 关键帧图片若用于视频参考，提交时会显式携带 `target_ratio + resolution_profile`
- 后端根据当前默认图片模型 capability 解析对应 `size`，保证关键帧画幅与目标视频保持一致
- 工作室会展示当前关键帧规格预览：`ratio + resolution_profile -> size`
- 视频提示词预览当前会额外暴露 `action_beats / previous_shot_summary / next_shot_goal / continuity_guidance`
- 视频提示词预览当前会额外暴露 `composition_anchor`
- 视频提示词预览当前会额外暴露 `screen_direction_guidance`
- `action_beats` 由当前镜头剧本摘录、镜头描述与对白规则化提炼，用于降低“像静态画面说明”的问题
- continuity 字段由相邻镜头摘要生成，用于降低镜头切换时的突兀感
- `composition_anchor` 由景别、运镜、主场景、主角色与相邻镜头关系规则化生成，用于降低构图和轴线突变
- `screen_direction_guidance` 由机位角度、对白关系、相邻镜头场景连续性规则化生成，用于降低人物翻面与反打跳轴
- 视频 prompt pack 会结合当前/相邻镜头剧本与项目角色库追加“角色身份锚点”，使 text-only 视频生成仍能保持同名角色身份、年龄感、发型、服装和气质，并避免新入画角色替代上一镜头主体
- 可灵中转当前使用 `kling-v3-omni`；首帧与尾帧分别发送 `first_frame / end_frame` 类型，额外角色参考图只发送 `image_url`，不再发送中转接口拒绝的旧值 `type=reference`
- 若视频模板未显式消费这些 guidance，系统会在模板渲染结果后自动补一段稳定的“镜头执行约束”，避免新字段只存在于 preview pack 中
- 即便视频走手动 prompt 分支，系统当前也会追加同一层 guidance 补强，避免手动文本完全绕过镜头连续性与构图约束
- 视频最终 prompt 当前会统一追加轻量原创角色约束，保留当前设定与镜头连续性，并要求使用自然原创、通用面部特征，避免品牌标识、文字水印或可识别商标进入画面
- 分镜帧 `frame-render-prompt` 当前也会把 `director_command_summary` 与必要的 `continuity_guidance` 轻量补入最终图片提示词
- 分镜帧 `frame-render-prompt` 当前也会把必要的 `frame_specific_guidance` 作为“当前帧职责”候选补入最终图片提示词
- 分镜帧 `frame-render-prompt` 当前也会把 `composition_anchor` 轻量补入最终图片提示词
- 分镜帧 `frame-render-prompt` 当前也会把 `screen_direction_guidance` 轻量补入最终图片提示词
- 分镜帧最终图片提示词会按参考图类型追加统一的“参考图使用规则”：
  - 若本次存在 `character` 参考图，参考图说明区会先写入人物身份锁定，再列出每张图的具体职责；这样身份规则会出现在导演指令、剧情描述和服装 / 场景 / 道具规则之前，避免被后面的长文本冲淡
  - `character` 参考图只负责人物身份、脸型、五官、发型、气质、体态与身份一致性；系统不会默认额外生成角色脸部辅助图，避免清晰角色图被模型理解为多张身份来源后发生融合或换脸
  - `costume` 参考图只负责服装款式、颜色、纹样、材质与层次，并显式忽略其中的人脸、发型、姿势、手持物与背景
  - `scene` 参考图只负责空间结构、时代氛围、光线、色调、背景陈设与环境质感，并显式忽略其中的人物、服装、动作与临时道具
  - `prop` 参考图只负责道具造型、材质、尺寸感、颜色与使用方式，并显式忽略其中的人物、手、脸、服装与背景
  - 多类型参考图冲突时，身份以角色图为最高优先级，服装以服装图为最高优先级，环境以场景图为最高优先级，道具以道具图为最高优先级，不同类型参考图不得互相覆盖职责
- 分镜帧最终图片提示词当前只在参考图说明区使用 `图1 / 图2` 等稳定图号，剧情正文继续保留角色、服装、场景、道具的原始名称
  - 这样避免把“艾铃原本……”替换成“图1原本……”造成模型同时把图号理解为图片引用和剧情人物
  - 参考图说明会明确写成“第 1 张输入参考图（图1，名称）”，用于和上传图片顺序对齐
- 分镜帧图片生成在上传参考图前会按资产类型做传输隔离：
  - `character` 参考图保持原始图片字节，作为人物身份和脸部特征的唯一来源，不再自动复制或裁剪成额外参考图
  - `costume` 参考图仍按原顺序上传，但会在服务端遮蔽上中部头脸区域，只保留服装款式、颜色、纹样、材质与层次，避免服装模特的人脸与角色图竞争导致换脸
  - 该处理不减少或增加用户关联参考图数量：关联了角色、场景、道具、服装中的几个有效图片，本次任务就上传几个；若解析数量不一致，会在供应商调用前失败
- 首帧、关键帧、尾帧分别在各自的 `ShotFrameImage.reference_assets` 中保存参考资产快照：
  - 三种帧可独立选择角色、场景、道具与服装，修改其中一帧不会覆盖另外两帧
  - 参考资产快照以 `type + id` 作为稳定身份；当同一角色、场景、道具或服装更新了最新图片时，工作室会用实体当前 `file_id` 刷新展示与提交，正式生成会把新 `file_id` 写回当前帧位
  - 创建图片任务时只提交当前 `frame_type` 已选择的参考资产，并把本次实际选择写回对应帧位
  - 未保存帧级配置时该帧参考资产为空，不从镜头级关联自动继承；首次选择素材时自动创建对应帧位
  - 单张生成、快捷键生成与批量生成都从目标帧的 `reference_assets` 取值，不再读取镜头级通用关联
  - 提示词预览和正式生成都会在后端校验请求素材集合与目标帧配置一致；校验关注 `type + id`，允许同一资产的 `file_id` 随最新图片刷新；发现跨帧或旧入口混入素材时返回冲突，不调用供应商
- OpenAI 兼容图片编辑接口当前使用 `multipart/form-data` 上传参考图：
  - 存在参考图时走 `/images/edits`
  - `gpt-image-2` 多张本地参考图按官方契约作为重复的 `image[]` 文件字段上传；旧兼容模型继续使用 `image`
  - 角色、服装、场景、道具等多类型参考图使用同一条上传链路；当前镜头关联了几个有效参考图，本次任务就必须传几个
  - 当前镜头未关联的资产不会凭空补入参考图，也不会要求上传
  - 若本次任务提交的关联参考图数量与实际展开上传的图片文件数量不一致，任务会在供应商调用前失败，不会静默退化为少图或无图生成
  - A 方案脸部二次修正当前已默认禁用：实测 `mask + 角色参考图` 虽然能成功调用图片编辑接口，但模型容易把局部身份校准理解为二次重绘，导致原本较像的第一阶段成片反而被换成新脸
  - 当前正式生成只保留首轮多参考图生成结果，不再把生成图回传给模型做二次修脸；任务结果也不会再写入新的 `face_correction=succeeded` 来误导判断
  - `gpt-image-2` 保留参考图原始分辨率、格式与字节，不再预先缩到长边 1024 或转为有损 JPEG，避免角色脸部细节在送模前损失
  - `gpt-image-2` 的所有图片输入由模型自动按高保真处理，因此不发送官方不允许修改的 `input_fidelity`；旧版兼容模型仍按能力默认使用 `input_fidelity=high`
  - 图片请求若在供应商返回响应前遇到临时网络 / 网关断连，会按统一重试策略自动重试，避免一次 `Server disconnected without sending a response` 直接让任务失败
  - 参考图编辑请求使用供应商 SSE 保持长连接，后台逐条消费事件；收到 `*.completed` 完整图片事件后立即落库，不再等待兼容网关发送 `[DONE]` 或正常关闭连接，避免约两分钟后断线丢失已生成结果
  - 服务启动时会把超过 10 分钟没有更新、仍处于 pending/running/streaming 的图片任务转为失败，避免进程重载留下的僵尸任务让分镜永久显示“生成中”
  - 请求日志会记录 `uploaded_image_count`、`uploaded_image_bytes` 与 `multipart_image_field`，用于排查供应商是否实际接收到参考图文件
- 分镜帧图片任务创建成功后，工作室弹窗会立即关闭并释放按钮 loading；后续进度、成功、失败与取消统一由右下角任务中心追踪，不在业务弹窗内进行长轮询
- 分镜帧图片卡片会按创建出的任务 ID 继续轮询状态：任务成功后刷新当前帧图片缩略图，任务失败或取消后同步卡片状态并停止 loading，避免本地卡片长期停留在“排队中 / 0%”
- 本地 SQLite 开发模式下，图片任务会投递到本地后台线程执行；executor 信息回写失败不会让创建接口误报失败，若本地线程入口异常，会尽量把任务从 `pending` 标记为 `failed`，避免静默悬挂
- 图片任务恢复会区分两类异常：活动态任务超过 10 分钟无更新会失败；`pending` 且没有 executor、没有 `started_at` 的图片任务超过 1 分钟会判定为派发丢失并失败。runtime summary 查询前会执行这段轻量恢复，避免旧僵尸任务继续污染“生成中”状态
- 当绑定 `costume` 参考图时，系统会追加服装一致性硬规则：
  - 服装参考图的颜色、款式、纹样和层次优先于剧情词、时代词与类型片常识
  - 即使剧情出现“大婚 / 婚房 / 嫁娶 / 退婚”等文字，也不得把服装自动改红或替换为其他婚服
- 分镜帧若包含人物，最终图片提示词会追加人物面部质量约束：
  - 现实 / live-action 风格要求保留清晰可辨的完整自然五官与影视级写实质感，但人物脸部必须直接比照角色参考图的图像本身，不能只根据文字描述想象新面孔
  - 动漫等非现实风格继续使用原创虚构人脸与轻微风格化影视概念参考图约束，避免真实摄影照片质感以及真实个人 / 明星 / 版权角色相似
  - 若存在 `character` 参考图，系统会在参考图使用规则最前面追加人物身份锁定：角色参考图定义对应角色的人物身份与脸部特征；身份判断必须以输入参考图的可见图像为准，文字中的脸型、五官、发型、气质等词只作为核对维度，不作为重新想象人物外貌的描述词；当前生成应按同一位角色演员连续出演来生成，而不是生成相似演员或重新设计角色；服装、场景、道具参考图中的人脸不得作为身份来源
  - 因此关键帧提示词预览中看到的高优先级导演约束，不再只停留在调试展示
  - 最终提交给图片模型的 render prompt 会显式带上这层收敛后的约束、当前帧职责、构图重心与朝向/视线要求
- 对于首帧，当前系统会优先强调“触发瞬间 / 初始反应 / 未完成态”表达，避免提示词直接落到后续完成动作或最终姿态
- 为避免 prompt 膨胀，这层收敛当前最多只保留 3 条 guidance
- 当前默认优先级为：`director_command_summary` > `continuity_guidance` > `screen_direction_guidance` > `composition_anchor`
- 这层优先级还会按 `frame_type` 做动态微调：
  - `first` 更偏向保留 `composition_anchor`
  - `key` / `last` 更偏向保留 `screen_direction_guidance`
  - 目的是让建立镜头先稳住空间，对峙/反打/收束镜头先稳住视线与左右轴线
- 前端关键帧提示词预览当前会直接展示：
  - “基础提示词生成依据”，用于说明 guidance 主要先服务于上游基础提示词生成
  - “最终图片提示词收敛结果”，用于说明只有少量 guidance 会被再次补进最终图片 prompt
  - 最终 render prompt 实际保留了哪些 guidance
  - 哪些 guidance 因压缩策略被舍弃
  - 每条 guidance 被保留或压缩的原因说明
  - 同时提供更短的 `reason_tag`，例如 `首帧保空间`、`关键帧保轴线`
  - 这样可以直接解释“为什么预览里有 4 条规则，但最终 prompt 只用了 3 条”
- 图片任务提交后，`render_context` 当前也会保留这组 guidance 决策详情
  - 因此任务链与预览链现在共享同一份“保留 / 压缩 / 原因”上下文
- 项目级信息提取当前还会输出镜头语言默认建议
  - `semantic_suggestion.camera_shot`
  - `semantic_suggestion.angle`
  - `semantic_suggestion.movement`
  - `semantic_suggestion.duration`
  - `semantic_suggestion.action_beats`
- `extract / extract-async` 在同步资产候选与对白候选之外，会按镜头序号将上述默认建议回写到 `ShotDetail`
  - 因此 `camera_shot / angle / movement / duration` 不再只依赖分镜写库时的硬编码初始值
  - `action_beats` 也会作为镜头动作拍点真值回写到 `ShotDetail`
  - 工作室中的镜头语言微调，修改的也是这同一份 `ShotDetail` 真值
- 分镜准备页聚合状态当前也会显式返回：
  - `basic_info_ready`
  - `semantic_defaults_ready`
  - `action_beats_ready`
  - `action_beats_count`
  - `action_beat_phases`
  - `ready_for_generation`
  - 其中 `ready_for_generation` 表示“准备页视角下可进入生成”，不等同于单纯的 `shot.status = ready`
- 视频链当前会优先消费 `ShotDetail.action_beats`
  - 只有在镜头尚未确认动作拍点时，才回退到基于 `script_excerpt + description + dialogue` 的规则化提炼
- 关键帧链当前也会优先消费 `ShotDetail.action_beats`
  - 后端会先对动作拍点做一层轻量 `trigger / peak / aftermath` 推断
  - 首帧优先消费触发阶段拍点
  - 关键帧优先消费峰值阶段拍点
  - 尾帧优先消费收束阶段拍点
- 视频 prompt 预览当前也会直接暴露这层阶段推断结果
  - 因此视频链与关键帧链现在会用同一套 `trigger / peak / aftermath` 标签来展示镜头内部动作过程

### `asset_image`

当前资产图片生成已开始迁移到：

- `build_base`
- `build_context`
- `derive_preview`
- `build_submission`

当前 actor / character / scene / prop / costume 图片的 render / submit 已开始走这套结构。

## 底层渲染组件约定

当前旧的图片兼容层已经移除，新的生成准备编排统一以以下目录为主入口：

- `generation/frame`
- `generation/video`
- `generation/asset_image`

其中仅保留 `shot_video_prompt_pack` 作为视频 pack 与模板渲染的底层组件：

- 它负责构建 `ShotVideoPromptPackRead`
- 它负责模板渲染所需的底层函数
- 它不再承担视频预览 / 提交的主编排入口职责

## 前端当前结构

### `useGenerationDraft`

当前前端已提供统一 hook：

```text
front/src/pages/aiStudio/hooks/useGenerationDraft.ts
```

该 hook 统一管理：

- `base`
- `context`
- `derived`
- `state`
- `deriveNow`
- `submitNow`
- `hydrate`
- `resetDerived`

### 当前已接入页面

#### 分镜工作室

`ChapterStudio` 当前已开始将：

- 关键帧提示词预览
- 视频提示词预览

接入 `useGenerationDraft`，逐步统一为：

- 用户编辑 `base`
- 页面维护 `context`
- 系统展示 `derived`
- 提交前通过 `submitNow()` 自动确保 `derived` 为最新结果

当前关键帧图片生成与视频生成都已经接入这套提交语义：

- 若基础提示词或上下文已变化，会先重新 `derive`
- 再使用最新的 `derived` 结果提交任务
- 页面不再单独维护一套“提交前再手动 render”的旁路逻辑

#### 资产编辑页

`AssetEditPageBase` 当前已开始将资产图片提示词预览与提交接入 `useGenerationDraft`。

因此，角色、演员、场景、道具、服装等资产编辑入口，已共享同一套生成准备心智模型。

其中，角色详情页也已收口到与演员 / 场景 / 道具 / 服装相同的资产编辑入口模型，不再单独维护一套角色图片生成入口逻辑。

当前资产图片生成提交也已统一为：

- 页面维护 `base + context`
- `submitNow()` 在提交前自动保证 `derived` 最新
- 任务创建使用最新的 `derived.prompt + derived.images`
- 调试信息默认收起，仅在用户主动展开时展示上下文与质量校验细节

## 当前边界

### 任务中心

任务中心保持“通用、轻量”的原则：

- 展示任务状态、进度、成功失败、取消与回跳入口
- 不承载业务级上下文摘要
- 不承载提示词调试详情

### 不属于该架构的模块

以下模块当前不属于“生成准备架构”：

1. 脚本处理类任务
2. 分镜编辑页的信息提取确认流
3. 任务中心

这些模块有独立职责，不参与当前的 `Base Draft / Context / Derived Preview / Submission Payload` 收敛。
