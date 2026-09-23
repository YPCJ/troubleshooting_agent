# troubleshooting_agent 前端接入后端接口设计（v1）

## 1. 目标

为前端 B/S 工作台提供稳定的后端接口层，支持：

- 多用户 + RBAC
- 多 Session 并发（单页面多 Tab）
- Session 级模型选择（Gemini/OpenAI）
- 实时消息流、工具调用轨迹、结果产物管理

本设计用于替代“仅通过 CLI 参数 `--llm` 控制模型”的运行方式，保留 CLI 作为调试入口。

当前后端同时承载两种执行路径：通用 Agent Runtime（`fault_diagnoses_agent` 的 ReAct + 工具循环）与 SBC LangGraph 受控故障树排查（`backend/agents/sbc_network_troubleshooting/`）。后者是产品主体，前者是其运行的底层框架，详见 `docs/sbc_network_troubleshooting_langgraph_design.md`。

## 2. 关键设计决策

1. 模型配置从“进程级”改为“Session 级”
   - 每个 Session 持久化 `provider/profile/model`。
   - 禁止依赖全局环境变量承载当前会话模型状态，避免多用户串扰。

2. 统一后端编排层
   - 前端仅调用 HTTP/SSE 接口，不直接执行脚本。
   - 后端通过统一 `llm` 适配层分发 OpenAI/Gemini。

3. CLI 角色调整
   - `fault_diagnoses.py --llm ...` 作为本地调试入口继续保留。
   - 生产接入路径以 API 为主。

## 3. 架构分层

1. Frontend（Web）
2. API Gateway / Backend（鉴权、权限、会话编排）
3. Agent Runtime（任务执行、工具调度、流式事件）
4. LLM Adapter（provider 抽象：Gemini/OpenAI/未来扩展）
5. Storage（Session/Message/ToolCall/Artifact/SkillVersion）

## 4. 核心对象（最小集）

- `Session`
  - `id`, `owner_id`, `app_id`, `status`
  - `model_provider`, `model_profile`, `model_name`
  - `created_at`, `updated_at`
- `Message`
  - `id`, `session_id`, `role`, `content`, `created_at`
- `ToolCall`
  - `id`, `session_id`, `name`, `args_json`, `result_json`, `status`, `created_at`
- `Artifact`
  - `id`, `session_id`, `type`, `path`, `mime_type`, `size`, `checksum`, `created_by`, `created_at`

## 5. API 设计（当前实现，对齐 `backend/server.py`）

> 本节内容为 `backend/server.py` 当前实际实现的接口。历史设计与实现已有出入（分组口径、字段名、部分端点未落地等），一律以此为准；完整契约见 `docs/openapi.v0.2.yaml`。

## 5.1 鉴权与用户

- `POST /api/auth/register`：账号密码注册
- `POST /api/auth/login`：返回 `{access_token, role, expires_at}`
- `POST /api/auth/logout`
- `GET /api/me`：当前用户名与角色
- `POST /api/me/password`：修改自己的密码
- `GET /api/users`（管理员）、`POST /api/users`、`PATCH /api/users/{username}`、`DELETE /api/users/{username}`、`POST /api/users/{username}/password`

角色为三级：`super_admin` / `admin` / `user`，而非早期设计的二级角色。

## 5.2 模型与配置

- `GET /api/models/providers`：动态返回 provider 注册表中的可用 provider
- `GET /api/models/profiles`：返回 `{items, default_profile}`
- `POST /api/models/profiles`、`PATCH /api/models/profiles/{id}`、`DELETE /api/models/profiles/{id}`（管理员）；创建后基础参数不可变，PATCH 仅更新采样参数
- `POST /api/models/profiles/{id}/default`（管理员，设为默认）
- `GET /api/models/catalog?provider={provider}&q={keyword}`：通过统一 provider 接口查询可用模型名
- `GET /api/models/gemini/models`、`GET /api/models/aliyun/models`：保留的兼容接口
- `POST /api/models/test-connection`：使用入口绑定的指定模型执行最小 Hello world 推理，返回实际内容、耗时和 Token 用量

## 5.3 Session 生命周期

- `POST /api/sessions`
  - 入参：`app_id`, `model_profile_id?`, `title?`（未指定 `model_profile_id` 时回落系统默认 profile）
- `GET /api/sessions`：返回 `{active: [...], archived: [...]}` 两组（不是运行中/最近/归档三组），普通用户仅本人，管理员/超管可全量
- `GET /api/sessions/{session_id}`、`DELETE /api/sessions/{session_id}`
- `PATCH /api/sessions/{session_id}/archive`、`PATCH /api/sessions/{session_id}/activate`
- `POST /api/sessions/{session_id}/control`
  - 入参：`action` in `stop|pause|resume|cancel|rerun|archive|activate`

## 5.4 消息与流式输出

- `GET /api/sessions/{session_id}/messages`：返回该 Session 全部消息
- `POST /api/sessions/{session_id}/messages`
  - 入参：`content`
- `GET /api/sessions/{session_id}/events`（SSE，鉴权支持 `Authorization` header 或查询参数 `access_token`）
- `GET /api/sessions/{session_id}/sbc-event-selection`、`POST /api/sessions/{session_id}/sbc-event-selection`
  - SBC LangGraph 专属：当图在 `interrupt` 节点等待人工从候选异常事件中选择时使用，`POST` 入参 `event_id`

## 5.5 Skills / Tools / 结果中心

- `GET /api/skills`
- `PATCH /api/skills/{skill_id}`：更新 `markdown` 正文（当前无版本历史、无新增/删除接口）
- `GET /api/tools`
- `PATCH /api/tools/{tool_name}`：仅支持 `{enabled: bool}` 开关（管理员），无新增/删除工具接口
- `GET /api/sessions/{session_id}/records?kind=`：会话内技能/工具调用记录
- `GET /api/sessions/{session_id}/preview?record_id=`：预览某条记录关联的文件/技能内容
- `GET /api/sessions/{session_id}/artifacts/{artifact_id}/content`：下载/预览产物文件
- `GET /api/artifacts?session_id=&artifact_type=`：跨会话检索产物列表
- 未实现：产物的 `DELETE` / 批量归档 (`archive`) / 恢复 (`restore`)

## 6. 权限规则（接口层强制）

- 普通用户
  - 仅可访问本人 Session、消息、产物
  - 可编辑 Skill 的 Markdown 文档
  - 不可新增/删除 Skill 与 Tool
- 管理员
  - 可访问全量数据
  - 当前可管理用户、模型 profile 和 Tool 启停；Skill 仍只有 Markdown 编辑接口
  - Skill/Tool 新增删除及模型可见性策略属于目标权限，当前没有对应完整接口

## 7. 与当前代码的衔接方案

1. 保留并复用 `llm/` 适配层（`factory + providers + profiles`）。
2. 在后端新增 `SessionRuntimeService`：
   - 接收 Session 级模型参数
   - 调用 `chat_reply/chat_reply_stream`
   - 产出标准事件流
3. 将 `fault_diagnoses.py` 中的交互循环拆分为可复用服务方法（而非仅 `input()` CLI 入口）。

## 8. 实施顺序（建议）

1. 固化接口契约（OpenAPI）
2. 完成 Session + Message + Artifact 表结构
3. 落地 `POST /sessions` + `/messages` + `/events` 主链路
4. 打通模型选择（Session 级）并接入前端“新建 Session”表单
5. 补齐权限、管理视图接口与回归测试

## 9. 非目标（本阶段不做）

- 多租户隔离
- 分布式执行调度中心
- 全链路可观测性平台化
