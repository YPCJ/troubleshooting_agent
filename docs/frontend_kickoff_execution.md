# 前端开工执行文档（v0.1）

> 状态说明（2026-09）：本文保留最初的实施顺序和交付标准。M0、M1 主链路已经落地；M2、M3 仅部分落地。下文的“交付标准”是验收目标，不等同于当前已经实现的能力。

## 1. 最小后端实现顺序（可支撑前端尽快联调）

目标：先打通“登录 -> 新建 Session -> 发送消息 -> 实时展示 -> 查看结果”的主链路。

### M0（接口骨架）

当前状态：✅ 已实现并接入前端。

1. `POST /api/auth/login`
2. `GET /api/me`
3. `GET /api/models/providers`
4. `GET /api/models/profiles`
5. `GET /api/skills`
6. `GET /api/tools`

交付标准：

- 前端可完成登录态初始化、用户角色加载、模型下拉加载、技能/工具列表展示（只读）。

### M1（Session 主链路）

当前状态：✅ 已实现并接入前端。实际会话列表接口返回 `active/archived` 两组，前端再组织展示。

1. `POST /api/sessions`
2. `GET /api/sessions`
3. `GET /api/sessions/{session_id}`
4. `POST /api/sessions/{session_id}/messages`
5. `GET /api/sessions/{session_id}/events`（SSE）

交付标准：

- 前端可创建新会话；
- 会话列表可按“运行中/最近/归档”展示；
- 可发送消息并流式接收 `message.delta` / `tool.call` / `tool.result` / `run.done`。

### M2（会话控制与结果中心）

当前状态：🟦 部分实现。控制接口目前只更新 Session 状态，不会中断、恢复或重新启动正在执行的工作线程，因此不满足“硬暂停/继续/取消/从头重跑”的验收语义。结果中心支持按类型和 Session ID 检索及产物预览/下载，但不支持按时间检索和聚合统计。

1. `POST /api/sessions/{session_id}/control`（pause/resume/cancel/rerun）
2. `GET /api/artifacts`

交付标准：

- 支持硬暂停、继续、取消、从头重跑；
- 结果中心可按类型/会话/时间检索并反查来源 Session。

### M3（管理能力）

当前状态：🟦 部分实现。Skill Markdown 可覆盖保存；Tool 仅支持管理员启停。Tool 新增/删除、Skill 版本历史、统一错误码均未实现。

1. `PATCH /api/skills/{skill_id}`（已实现；覆盖保存 Markdown，不创建历史版本）
2. `PATCH /api/tools/{tool_name}`（已实现；仅支持 `{enabled: bool}`）
3. `POST /api/tools`（未实现，管理员）
4. `DELETE /api/tools/{tool_id}`（未实现，管理员）

交付标准：

- 普通用户可编辑技能 Markdown；
- 管理员可增删工具；
- 权限不足时返回统一错误码和提示文案。

---

## 2. 前端并行开发切片（Mock 优先）

目标：即使后端未全部完成，前端也能并行推进页面和交互。

### Slice A（优先，最适合先 Mock）

1. 登录页（账号密码、本地校验）
2. 主工作台壳体（三栏布局）
3. Session 列表分组（运行中/最近/归档）
4. 主视图切换（Session / Skills / Tools / 结果中心）
5. “返回当前 Session”固定入口

依赖：

- 可完全 Mock，本地 JSON 即可。

### Slice B（与后端 M1 并行）

1. 新建 Session 视图（App 下拉、模型下拉、可选文件输入）
2. Session 运行视图（消息流、工具调用流、状态）
3. SSE 事件渲染器（先接 Mock EventSource，再切真实接口）

依赖：

- M0 + M1 接口就绪后可快速切换真实数据源。

### Slice C（与后端 M2 并行）

1. 会话控制区（暂停/继续/取消/重跑）
2. 结果中心筛选与预览列表

依赖：

- M2 接口就绪。

### Slice D（与后端 M3 并行）

1. Skills Markdown 编辑（版本保存入口）
2. Tools 管理（管理员增删）
3. 模型管理（管理员视图）

依赖：

- M3 接口和 RBAC 约束就绪。

---

## 3. 开发建议（执行层）

1. 先用 `docs/openapi.v0.2.yaml` 生成 TS 类型与 API Client（或手写最小 client）。
2. 前端数据层统一一层 `api/` 封装，禁止页面直接 fetch。
3. 所有 Mock 数据和真实 API 响应结构保持一致，避免二次改造。
4. SSE 采用统一事件总线（避免页面内散落监听逻辑）。
5. 权限判断统一在路由层 + 按钮层双层处理。
