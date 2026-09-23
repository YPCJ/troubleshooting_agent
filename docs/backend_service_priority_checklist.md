# 后端服务实现优先级清单（对齐 OpenAPI v0.2）

> 状态标记基于 2026-09 对 `backend/server.py` 的实际路由核实。`[x]` = 已实现，`[ ]` = 未实现。

## P0（阻塞前端主链路，优先完成）

1. [x] `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/me`
2. [x] `GET /api/apps`
3. [x] `GET /api/models/providers`、`GET /api/models/profiles`
4. [x] `POST /api/sessions`、`GET /api/sessions`、`GET /api/sessions/{session_id}`
5. [x] `GET /api/sessions/{session_id}/messages`
6. [x] `POST /api/sessions/{session_id}/messages`
7. [x] `GET /api/sessions/{session_id}/events`（SSE）
8. [x] `POST /api/sessions/{session_id}/control`（实际支持 `stop|pause|resume|cancel|rerun|archive|activate`）
9. [ ] `POST /api/uploads`（未实现，前端文件上传按钮未接后端）

验收口径：
- 登录后可加载应用列表和模型列表；✅
- 可新建会话、发送消息、实时收流；✅
- 发送按钮可切换“发送/停止”并生效；✅
- 文件上传：❌ 尚未打通。

## P1（当前骨架右栏和结果中心）

1. [x] `GET /api/sessions/{session_id}/records`（`kind` 支持 `all/skills/tools`）
2. [x] `GET /api/artifacts`（按 `session_id`、`artifact_type` 检索，实际字段为 `artifact_id/filename/path/artifact_type/session_id`）
3. [ ] `GET /api/artifacts/{artifact_id}`（未实现为独立接口；产物内容改由 `GET /api/sessions/{session_id}/artifacts/{artifact_id}/content` 提供）
4. [ ] `GET /api/artifacts/{artifact_id}/preview`（未实现；会话内记录预览走 `GET /api/sessions/{session_id}/preview?record_id=`）
5. [ ] `GET /api/artifacts/{artifact_id}/download`（未实现，见上）

验收口径：
- Session 右栏“调用记录/输出结果”可按筛选项取数；✅
- 结果中心支持检索、预览、下载、反查 session；🟦 部分支持，路径与本清单原设计不同（见上）。

## P2（管理能力）

1. Skills：
   - [ ] `POST /api/skills`
   - [ ] `DELETE /api/skills/{skill_id}`
   - [x] `PATCH /api/skills/{skill_id}`（仅更新 `markdown` 正文，注意实际方法是 `PATCH` 不是设计文档写的 `PUT`；无元数据更新）
   - [ ] `GET /api/skills/{skill_id}/markdown/versions`
2. Tools：
   - [ ] `POST /api/tools`
   - [x] `PATCH /api/tools/{tool_name}`（仅支持 `{enabled: bool}` 开关，不支持通用参数配置）
   - [ ] `DELETE /api/tools/{tool_id}`
3. Models：
   - [x] `POST /api/models/profiles`
   - [x] `PATCH /api/models/profiles/{profile_id}`
   - [x] `DELETE /api/models/profiles/{profile_id}`
   - [x] `POST /api/models/profiles/{profile_id}/default`（设默认，清单原先没列但已实现）
   - [x] `POST /api/models/test-connection`
4. User settings：
   - [x] `POST /api/me/password`（实际方法是 `POST`，不是清单写的 `PATCH /api/me/settings`）
   - [ ] `PATCH /api/me/settings`（除密码外的其他用户设置未实现）

验收口径：
- 管理员权限接口可用，普通用户正确拦截；✅
- 模型管理可新增、复制、删除和设默认；已创建入口仅允许修改采样参数；连通性测试：✅
- 用户设置与修改密码流程可闭环：🟦 仅密码修改已实现。
- Skill/Tool 的新增、删除、Markdown 版本历史：❌ 均未实现，当前只能启停/编辑正文。

## P3（结果“管理”深化）

1. [ ] `DELETE /api/artifacts/{artifact_id}`
2. [ ] `POST /api/artifacts/archive`
3. [ ] `POST /api/artifacts/restore`

验收口径：全部未实现；产物目前没有归档/恢复/删除操作，仅能随会话归档间接管理。

## 补充：清单外的真实接口

- `GET/POST /api/sessions/{session_id}/sbc-event-selection`：SBC LangGraph 受控排查在 `interrupt` 节点等待人工从候选异常事件中选择时使用，是 SBC 主体场景的关键接口，本清单最初未覆盖。
- `PATCH /api/sessions/{session_id}/archive`、`PATCH /api/sessions/{session_id}/activate`：会话归档/恢复，独立于 `control` 接口。
- `POST /api/auth/register`、`GET/POST/PATCH/DELETE /api/users*`：用户管理相关接口，清单原先归入 P0 的鉴权部分但未细化到位。

## 横切能力（与 P0 并行）

1. [ ] 错误码与提示文案统一（OpenAPI `ErrorResponse`）——当前错误响应仅有 `{message}` 字段，无统一错误码
2. [ ] 分页/筛选/排序参数统一——多数列表接口暂无分页
3. [ ] 审计日志字段统一（变更人、时间、对象、前后摘要）——未实现
4. [ ] token usage 回传（用于“模型 + token”展示）——`message_payload` 已有 `usage.total_tokens` 字段，但前端展示与统计尚未完整对齐
