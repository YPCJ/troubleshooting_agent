# fault_assistant_AI 前端接入后端接口设计（v1）

## 1. 目标

为前端 B/S 工作台提供稳定的后端接口层，支持：

- 多用户 + RBAC
- 多 Session 并发（单页面多 Tab）
- Session 级模型选择（Gemini/OpenAI）
- 实时消息流、工具调用轨迹、结果产物管理

本设计用于替代“仅通过 CLI 参数 `--llm` 控制模型”的运行方式，保留 CLI 作为调试入口。

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

## 5. API 设计（首期）

## 5.1 鉴权与用户

- `POST /api/auth/login`：账号密码登录，返回 token
- `POST /api/auth/logout`
- `GET /api/me`：当前用户与角色

## 5.2 模型与配置

- `GET /api/models/providers`：可用 provider 列表
- `GET /api/models/profiles`：可用 profile 列表（含默认值、可见范围）

## 5.3 Session 生命周期

- `POST /api/sessions`
  - 入参：`app_id`, `title?`, `model_provider?`, `model_profile?`, `model_name?`, `inputs?`
  - 行为：创建 Session，若未指定模型则回落系统默认（gemini_default）
- `GET /api/sessions`：按分组返回（运行中/最近/归档），普通用户仅本人，管理员可全量
- `GET /api/sessions/{session_id}`
- `POST /api/sessions/{session_id}/control`
  - 入参：`action` in `pause|resume|cancel|rerun`
  - 规则：`pause` 为硬暂停；`rerun` 为从头重跑

## 5.4 消息与流式输出

- `POST /api/sessions/{session_id}/messages`
  - 入参：`content`, `attachments?`
  - 返回：`message_id` + `run_id`
- `GET /api/sessions/{session_id}/events`（SSE）
  - 按顺序推送：`message.delta`、`tool.call`、`tool.result`、`artifact.created`、`run.done`、`run.error`

SSE 事件示例：

```json
{
  "type": "tool.call",
  "session_id": "sess_xxx",
  "run_id": "run_xxx",
  "timestamp": "2026-07-22T11:00:00Z",
  "payload": {
    "name": "data_query",
    "arguments": {"sat_id": "01"}
  }
}
```

## 5.5 Skills / Tools / 结果中心

- `GET /api/skills`
- `PUT /api/skills/{skill_id}/markdown`（普通用户可编辑 md；增删仅管理员）
- `GET /api/tools`
- `POST /api/tools` / `DELETE /api/tools/{tool_id}`（管理员）
- `GET /api/artifacts`（支持按 app/session/type/time/user 检索）

## 6. 权限规则（接口层强制）

- 普通用户
  - 仅可访问本人 Session、消息、产物
  - 可编辑 Skill 的 Markdown 文档
  - 不可新增/删除 Skill 与 Tool
- 管理员
  - 可访问全量数据
  - 可管理用户、Skill、Tool、模型可见性

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
