# 后端服务实现优先级清单（对齐 OpenAPI v0.2）

## P0（阻塞前端主链路，优先完成）

1. `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/me`
2. `GET /api/apps`
3. `GET /api/models/providers`、`GET /api/models/profiles`
4. `POST /api/sessions`、`GET /api/sessions`、`GET /api/sessions/{session_id}`
5. `GET /api/sessions/{session_id}/messages`
6. `POST /api/sessions/{session_id}/messages`
7. `GET /api/sessions/{session_id}/events`（SSE）
8. `POST /api/sessions/{session_id}/control`（至少支持 `stop`）
9. `POST /api/uploads`

验收口径：
- 登录后可加载应用列表和模型列表；
- 可新建会话、发送消息、实时收流；
- 发送按钮可切换“发送/停止”并生效。

## P1（当前骨架右栏和结果中心）

1. `GET /api/sessions/{session_id}/records`（all/skills/tools）
2. `GET /api/artifacts`
3. `GET /api/artifacts/{artifact_id}`
4. `GET /api/artifacts/{artifact_id}/preview`
5. `GET /api/artifacts/{artifact_id}/download`

验收口径：
- Session 右栏“调用记录/输出结果”可按筛选项取数；
- 结果中心支持检索、预览、下载、反查 session。

## P2（管理能力）

1. Skills：
   - `POST /api/skills`
   - `PATCH /api/skills/{skill_id}`
   - `DELETE /api/skills/{skill_id}`
   - `PUT /api/skills/{skill_id}/markdown`
   - `GET /api/skills/{skill_id}/markdown/versions`
2. Tools：
   - `POST /api/tools`
   - `PATCH /api/tools/{tool_id}`
   - `DELETE /api/tools/{tool_id}`
3. Models：
   - `POST /api/models/profiles`
   - `PATCH /api/models/profiles/{profile_id}`
   - `DELETE /api/models/profiles/{profile_id}`
   - `POST /api/models/test-connection`
4. User settings：
   - `PATCH /api/me/settings`
   - `POST /api/me/password`

验收口径：
- 管理员权限接口可用，普通用户正确拦截；
- 模型管理可增改删并可测试连通性；
- 用户设置与修改密码流程可闭环。

## P3（结果“管理”深化）

1. `DELETE /api/artifacts/{artifact_id}`
2. `POST /api/artifacts/archive`
3. `POST /api/artifacts/restore`

验收口径：
- 可批量归档/恢复；
- 删除行为具备权限校验和审计记录。

## 横切能力（与 P0 并行）

1. 错误码与提示文案统一（OpenAPI `ErrorResponse`）
2. 分页/筛选/排序参数统一
3. 审计日志字段统一（变更人、时间、对象、前后摘要）
4. token usage 回传（用于“模型 + token”展示）
