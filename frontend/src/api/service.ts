import type { AppCard, ArtifactItem, ArtifactType, ModelProfile, RecordType, SessionGroups, SessionItem, SessionMessage, SessionRecord, SkillItem } from '../types/app'
import { API_BASE_URL, requestJson } from './client'

export type LoginResponse = {
  access_token: string
  role: 'super_admin' | 'admin' | 'user'
  expires_at?: string
}

export type LoginRequest = {
  username: string
  password: string
}

export type RegisterRequest = {
  username: string
  password: string
}

export type RegisterResponse = {
  username: string
  role: 'super_admin' | 'admin' | 'user'
}

export type UserAccount = {
  username: string
  role: 'super_admin' | 'admin' | 'user'
  isDisabled: boolean
  createdAt: string
  updatedAt: string
}

type AppDto = {
  app_id: string
  description?: string
  icon?: string
}

type SessionDto = {
  session_id: string
  title?: string
  status: SessionItem['status']
  updated_at?: string
  model_profile_id?: string
  model_name?: string
}

type SessionListResponse = {
  active: SessionDto[]
  archived: SessionDto[]
}

type MessageDto = {
  message_id: string
  role: SessionMessage['role']
  content: string
  kind?: SessionMessage['kind']
  model_profile_id?: string
  usage?: {
    total_tokens?: number
  }
}

type SendMessageResponse = {
  message_id: string
  run_id: string
}

export type SessionEvent = {
  id: string
  type: string
  session_id: string
  run_id: string
  timestamp: string
  payload: Record<string, unknown>
}

type RecordDto = {
  record_id: string
  record_type: string
  label: string
}

type ArtifactDto = {
  artifact_id: string
  filename: string
  path: string
  artifact_type: string
  session_id: string
}

type SkillDto = {
  skill_id: string
  markdown: string
}

type ModelProfileDto = {
  profile_id: string
  provider?: string
  model_name?: string
  base_url?: string
  temperature?: number
  top_p?: number
  top_k?: number
  max_output_tokens?: number
}

type UserAccountDto = {
  username: string
  role: 'super_admin' | 'admin' | 'user'
  is_disabled: boolean
  created_at: string
  updated_at: string
}

function mapApp(dto: AppDto): AppCard {
  return {
    id: dto.app_id,
    icon: dto.icon ?? '🧩',
    desc: dto.description ?? '未填写描述',
  }
}

function formatUpdated(raw?: string): string {
  if (!raw) return '未知'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function mapSession(dto: SessionDto): SessionItem {
  return {
    id: dto.session_id,
    name: dto.title ?? dto.session_id,
    status: dto.status,
    updated: formatUpdated(dto.updated_at),
    model: dto.model_name ?? dto.model_profile_id,
  }
}

function mapRecordType(raw: string): RecordType {
  if (raw === 'skill') return 'skill'
  if (raw === 'tool') return 'tool'
  return 'other'
}

function mapArtifactType(raw: string): ArtifactType {
  if (raw === 'document') return 'document'
  if (raw === 'image') return 'image'
  if (raw === 'data') return 'data'
  return 'other'
}

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  return requestJson<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function register(payload: RegisterRequest): Promise<RegisterResponse> {
  return requestJson<RegisterResponse>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function logout(token: string): Promise<void> {
  await requestJson<void>('/api/auth/logout', {
    method: 'POST',
    token,
  })
}

export async function fetchMe(token: string): Promise<{ username: string; role: 'super_admin' | 'admin' | 'user' }> {
  return requestJson<{ username: string; role: 'super_admin' | 'admin' | 'user' }>('/api/me', { token })
}

export async function fetchUsers(token: string): Promise<UserAccount[]> {
  const res = await requestJson<{ items: UserAccountDto[] }>('/api/users', { token })
  return res.items.map((item) => ({
    username: item.username,
    role: item.role,
    isDisabled: item.is_disabled,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  }))
}

export async function adminCreateUser(
  token: string,
  payload: { username: string; password: string; role?: 'admin' | 'user' },
): Promise<{ username: string; role: 'admin' | 'user' }> {
  return requestJson<{ username: string; role: 'admin' | 'user' }>('/api/users', {
    method: 'POST',
    token,
    body: JSON.stringify({
      username: payload.username,
      password: payload.password,
      role: payload.role ?? 'user',
    }),
  })
}

export async function updateUser(
  token: string,
  username: string,
  payload: { role?: 'admin' | 'user'; isDisabled?: boolean },
): Promise<UserAccount> {
  const res = await requestJson<UserAccountDto>(`/api/users/${username}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({
      role: payload.role,
      is_disabled: payload.isDisabled,
    }),
  })
  return {
    username: res.username,
    role: res.role,
    isDisabled: res.is_disabled,
    createdAt: res.created_at,
    updatedAt: res.updated_at,
  }
}

export async function deleteUser(token: string, username: string): Promise<void> {
  await requestJson<void>(`/api/users/${username}`, {
    method: 'DELETE',
    token,
  })
}

export async function changeMyPassword(token: string, payload: { currentPassword: string; newPassword: string }): Promise<void> {
  await requestJson<void>('/api/me/password', {
    method: 'POST',
    token,
    body: JSON.stringify({
      current_password: payload.currentPassword,
      new_password: payload.newPassword,
    }),
  })
}

export async function adminResetUserPassword(
  token: string,
  username: string,
  payload: { newPassword: string },
): Promise<void> {
  await requestJson<void>(`/api/users/${username}/password`, {
    method: 'POST',
    token,
    body: JSON.stringify({
      new_password: payload.newPassword,
    }),
  })
}

export async function fetchApps(token: string): Promise<AppCard[]> {
  const res = await requestJson<{ items: AppDto[] }>('/api/apps', { token })
  return res.items.map(mapApp)
}

export async function fetchSessions(token: string): Promise<SessionGroups> {
  const res = await requestJson<SessionListResponse>('/api/sessions', { token })
  return {
    active: res.active.map(mapSession),
    archived: res.archived.map(mapSession),
  }
}

export async function createSession(
  token: string,
  appId: string,
  modelProfileId?: string,
  title?: string,
): Promise<SessionItem> {
  const res = await requestJson<SessionDto>('/api/sessions', {
    method: 'POST',
    token,
    body: JSON.stringify({ app_id: appId, model_profile_id: modelProfileId, title }),
  })
  return mapSession(res)
}

export async function fetchSessionMessages(token: string, sessionId: string): Promise<SessionMessage[]> {
  const res = await requestJson<{ items: MessageDto[] }>(`/api/sessions/${sessionId}/messages`, { token })
  return res.items.map((item) => ({
    id: item.message_id,
    role: item.role,
    content: item.content,
    kind: item.kind ?? 'text',
    model: item.model_profile_id,
    tokens: item.usage?.total_tokens,
  }))
}

export async function sendSessionMessage(token: string, sessionId: string, content: string): Promise<SendMessageResponse> {
  return requestJson<SendMessageResponse>(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    token,
    body: JSON.stringify({ content }),
  })
}

export function subscribeSessionEvents({
  token,
  sessionId,
  runId,
  onEvent,
  onError,
}: {
  token: string
  sessionId: string
  runId?: string
  onEvent: (event: SessionEvent) => void
  onError?: (message: string) => void
}): () => void {
  const url = new URL(`${API_BASE_URL}/api/sessions/${sessionId}/events`)
  url.searchParams.set('access_token', token)
  if (runId) {
    url.searchParams.set('run_id', runId)
  }
  const source = new EventSource(url.toString())
  source.onmessage = (evt) => {
    try {
      const parsed = JSON.parse(evt.data) as SessionEvent
      onEvent(parsed)
    } catch {
      onError?.('收到无法解析的 SSE 事件')
    }
  }
  source.onerror = () => {
    onError?.('SSE 连接已中断')
  }
  return () => source.close()
}

export async function stopSession(token: string, sessionId: string): Promise<void> {
  await requestJson<void>(`/api/sessions/${sessionId}/control`, {
    method: 'POST',
    token,
    body: JSON.stringify({ action: 'stop' }),
  })
}

export async function archiveSession(token: string, sessionId: string): Promise<void> {
  await requestJson<void>(`/api/sessions/${sessionId}/archive`, {
    method: 'PATCH',
    token,
  })
}

export async function activateSession(token: string, sessionId: string): Promise<void> {
  await requestJson<void>(`/api/sessions/${sessionId}/activate`, {
    method: 'PATCH',
    token,
  })
}

export async function deleteSession(token: string, sessionId: string): Promise<void> {
  await requestJson<void>(`/api/sessions/${sessionId}`, {
    method: 'DELETE',
    token,
  })
}

export async function fetchSessionRecords(token: string, sessionId: string, kind: 'all' | 'skills' | 'tools'): Promise<SessionRecord[]> {
  const res = await requestJson<{ items: RecordDto[] }>(`/api/sessions/${sessionId}/records?kind=${kind}`, { token })
  return res.items.map((item) => ({
    id: item.record_id,
    type: mapRecordType(item.record_type),
    label: item.label,
  }))
}

export async function fetchArtifacts(token: string, params: { sessionId?: string; type?: 'all' | 'doc' | 'image' | 'data' }): Promise<ArtifactItem[]> {
  const search = new URLSearchParams()
  if (params.sessionId) search.set('session_id', params.sessionId)
  if (params.type && params.type !== 'all') {
    const mapped = params.type === 'doc' ? 'document' : params.type
    search.set('artifact_type', mapped)
  }
  const query = search.toString()
  const path = query ? `/api/artifacts?${query}` : '/api/artifacts'
  const res = await requestJson<{ items: ArtifactDto[] }>(path, { token })
  return res.items.map((item) => ({
    id: item.artifact_id,
    name: item.filename,
    path: item.path,
    artifactType: mapArtifactType(item.artifact_type),
    sessionId: item.session_id,
  }))
}

export async function fetchSkills(token: string): Promise<SkillItem[]> {
  const res = await requestJson<{ items: SkillDto[] }>('/api/skills', { token })
  return res.items.map((item) => ({
    id: item.skill_id,
    markdown: item.markdown,
  }))
}

export async function updateSkillMarkdown(token: string, skillId: string, markdown: string): Promise<void> {
  await requestJson<void>(`/api/skills/${skillId}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({ markdown }),
  })
}

export async function fetchModelProfiles(token: string): Promise<{ items: ModelProfile[]; defaultProfile: string }> {
  const res = await requestJson<{ items: ModelProfileDto[]; default_profile: string }>('/api/models/profiles', { token })
  return {
    items: res.items.map((item) => ({
      id: item.profile_id,
      provider: item.provider ?? '',
      modelName: item.model_name ?? '',
      baseUrl: item.base_url,
      temperature: item.temperature,
      topP: item.top_p,
      topK: item.top_k,
      maxOutputTokens: item.max_output_tokens,
    })),
    defaultProfile: res.default_profile,
  }
}

export async function updateModelProfile(
  token: string,
  profileId: string,
  payload: { modelName?: string; provider?: string; baseUrl?: string; temperature?: number; topP?: number; topK?: number; maxOutputTokens?: number },
): Promise<void> {
  await requestJson<void>(`/api/models/profiles/${profileId}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({
      model_name: payload.modelName,
      provider: payload.provider,
      base_url: payload.baseUrl,
      temperature: payload.temperature,
      top_p: payload.topP,
      top_k: payload.topK,
      max_output_tokens: payload.maxOutputTokens,
    }),
  })
}

export async function createModelProfile(
  token: string,
  payload: { profileId: string; modelName: string; provider: string; baseUrl?: string; temperature?: number; topP?: number; topK?: number; maxOutputTokens?: number },
): Promise<void> {
  await requestJson<void>('/api/models/profiles', {
    method: 'POST',
    token,
    body: JSON.stringify({
      profile_id: payload.profileId,
      provider: payload.provider,
      model_name: payload.modelName,
      base_url: payload.baseUrl,
      temperature: payload.temperature,
      top_p: payload.topP,
      top_k: payload.topK,
      max_output_tokens: payload.maxOutputTokens,
    }),
  })
}

export async function deleteModelProfile(token: string, profileId: string): Promise<void> {
  await requestJson<void>(`/api/models/profiles/${profileId}`, {
    method: 'DELETE',
    token,
  })
}

export async function setDefaultModelProfile(token: string, profileId: string): Promise<void> {
  await requestJson<void>(`/api/models/profiles/${profileId}/default`, {
    method: 'POST',
    token,
  })
}

export async function fetchAliyunModels(token: string, params?: { q?: string; profileId?: string }): Promise<string[]> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  if (params?.profileId) search.set('profile_id', params.profileId)
  const query = search.toString()
  const path = query ? `/api/models/aliyun/models?${query}` : '/api/models/aliyun/models'
  const res = await requestJson<{ items: string[] }>(path, { token })
  return res.items
}

export async function fetchGeminiModels(token: string, params?: { q?: string }): Promise<string[]> {
  const search = new URLSearchParams()
  if (params?.q) search.set('q', params.q)
  const query = search.toString()
  const path = query ? `/api/models/gemini/models?${query}` : '/api/models/gemini/models'
  const res = await requestJson<{ items: string[] }>(path, { token })
  return res.items
}
