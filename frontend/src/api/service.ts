import type { AppCard, ArtifactItem, ArtifactType, ModelProfile, RecordType, SBCSelectionRequest, SessionGroups, SessionItem, SessionMessage, SessionRecord, SkillItem, ToolItem } from '../types/app'
import { API_BASE_URL, parseErrorMessage, requestJson } from './client'

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
  run_status?: string
  active_run_id?: string | null
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
  round_summary?: {
    model_calls?: number
    total_tokens?: number
  }
}

type SendMessageResponse = {
  message_id: string
  run_id: string
  status: 'running'
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
  source_kind?: 'file' | 'skill' | 'other'
  source_name?: string
  source_path?: string
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

type ToolDto = {
  tool_name: string
  description?: string
  // Kept as a plain string: the backend owns the category vocabulary and may add
  // values the UI has not been taught yet, which must not break the mapping.
  category?: string
  enabled?: boolean
  available?: boolean
  apps?: string[]
}

type ModelProfileDto = {
  profile_id: string
  provider?: string
  model_name?: string
  base_url?: string
  sampling_mode?: 'provider_default' | 'stable' | 'flexible' | 'custom'
  output_mode?: 'provider_default' | 'custom_limit'
  verbosity?: 'low' | 'medium' | 'high' | null
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
    runStatus: dto.run_status,
    activeRunId: dto.active_run_id ?? undefined,
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
    roundSummary: item.round_summary
      ? {
          modelCalls: item.round_summary.model_calls ?? 0,
          totalTokens: item.round_summary.total_tokens ?? 0,
        }
      : undefined,
  }))
}

export async function sendSessionMessage(token: string, sessionId: string, content: string): Promise<SendMessageResponse> {
  return requestJson<SendMessageResponse>(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    token,
    body: JSON.stringify({ content }),
  })
}

export async function fetchSBCEventSelection(
  token: string,
  sessionId: string,
): Promise<SBCSelectionRequest | null> {
  const res = await requestJson<{ selection: SBCSelectionRequest | null }>(
    `/api/sessions/${sessionId}/sbc-event-selection`,
    { token },
  )
  return res.selection
}

export async function selectSBCEvent(
  token: string,
  sessionId: string,
  eventId: string,
): Promise<SendMessageResponse> {
  return requestJson<SendMessageResponse>(
    `/api/sessions/${sessionId}/sbc-event-selection`,
    {
      method: 'POST',
      token,
      body: JSON.stringify({ event_id: eventId }),
    },
  )
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
  const url = new URL(`${API_BASE_URL}/api/sessions/${sessionId}/events`, window.location.origin)
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
    sourceKind: item.source_kind,
    sourceName: item.source_name,
    sourcePath: item.source_path,
  }))
}

export async function fetchSessionPreview(
  token: string,
  sessionId: string,
  recordId: string,
): Promise<{
  recordId: string
  sourceKind: 'file' | 'skill' | 'other'
  sourceName: string
  sourcePath: string
  title: string
  content: string
  contentKind: 'markdown' | 'text'
}> {
  const res = await requestJson<{
    record_id: string
    source_kind: 'file' | 'skill' | 'other'
    source_name: string
    source_path: string
    title: string
    content: string
    content_kind: 'markdown' | 'text'
  }>(`/api/sessions/${sessionId}/preview?record_id=${encodeURIComponent(recordId)}`, { token })
  return {
    recordId: res.record_id,
    sourceKind: res.source_kind,
    sourceName: res.source_name,
    sourcePath: res.source_path,
    title: res.title,
    content: res.content,
    contentKind: res.content_kind,
  }
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

export async function fetchArtifactContent(
  token: string,
  artifact: Pick<ArtifactItem, 'id' | 'sessionId'>,
): Promise<{ blob: Blob; contentType: string }> {
  const response = await fetch(
    `${API_BASE_URL}/api/sessions/${encodeURIComponent(artifact.sessionId)}/artifacts/${encodeURIComponent(artifact.id)}/content`,
    {
      headers: {
        Accept: '*/*',
        Authorization: `Bearer ${token}`,
      },
    },
  )
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response))
  }
  return {
    blob: await response.blob(),
    contentType: response.headers.get('Content-Type') ?? '',
  }
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

const TOOL_CATEGORIES: ReadonlyArray<ToolItem['category']> = [
  'file',
  'shell',
  'data',
  'skills',
  'sbc',
  'other',
]

function toToolCategory(value: string | undefined): ToolItem['category'] {
  return TOOL_CATEGORIES.includes(value as ToolItem['category'])
    ? (value as ToolItem['category'])
    : 'other'
}

export async function fetchTools(token: string): Promise<ToolItem[]> {
  const res = await requestJson<{ items: ToolDto[] }>('/api/tools', { token })
  return res.items.map((item) => ({
    name: item.tool_name,
    description: item.description ?? '',
    category: toToolCategory(item.category),
    enabled: item.enabled ?? true,
    available: item.available ?? true,
    apps: item.apps ?? [],
  }))
}

export async function updateToolEnabled(token: string, toolName: string, enabled: boolean): Promise<ToolItem> {
  const res = await requestJson<ToolDto>(`/api/tools/${encodeURIComponent(toolName)}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({ enabled }),
  })
  return {
    name: res.tool_name,
    description: res.description ?? '',
    category: toToolCategory(res.category),
    enabled: res.enabled ?? true,
    available: res.available ?? true,
    apps: res.apps ?? [],
  }
}

export async function fetchModelProfiles(token: string): Promise<{ items: ModelProfile[]; defaultProfile: string }> {
  const res = await requestJson<{ items: ModelProfileDto[]; default_profile: string }>('/api/models/profiles', { token })
  return {
    items: res.items.map((item) => ({
      id: item.profile_id,
      provider: item.provider ?? '',
      modelName: item.model_name ?? '',
      baseUrl: item.base_url,
      samplingMode: item.sampling_mode,
      outputMode: item.output_mode,
      verbosity: item.verbosity ?? undefined,
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
  payload: {
    samplingMode: 'provider_default' | 'stable' | 'flexible' | 'custom'
    outputMode: 'provider_default' | 'custom_limit'
    verbosity: 'low' | 'medium' | 'high' | null
    temperature?: number
    topP?: number
    topK?: number
    maxOutputTokens?: number
  },
): Promise<void> {
  await requestJson<void>(`/api/models/profiles/${profileId}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({
      sampling_mode: payload.samplingMode,
      output_mode: payload.outputMode,
      verbosity: payload.verbosity,
      temperature: payload.temperature,
      top_p: payload.topP,
      top_k: payload.topK,
      max_output_tokens: payload.maxOutputTokens,
    }),
  })
}

export async function fetchModelCapabilities(
  token: string,
  params: { provider: string; modelName: string; profileId?: string },
): Promise<import('../types/app').ModelCapabilities> {
  const query = new URLSearchParams({ provider: params.provider, model_name: params.modelName })
  if (params.profileId) query.set('profile_id', params.profileId)
  const res = await requestJson<{
    provider: string
    model: string
    parameters?: Record<string, import('../types/app').ModelParameterCapability>
    exclusive_groups?: string[][]
    defaults_source?: string
    recommend_provider_defaults?: boolean
    sampling_presets?: Array<{ id: string; temperature?: number; top_p?: number }>
    verbosity?: { supported?: boolean; choices?: string[]; default?: string | null }
    output?: { omission_supported?: boolean; counts_reasoning_tokens?: boolean; recommended?: number | null }
  }>(`/api/models/capabilities?${query.toString()}`, { token })
  return {
    provider: res.provider,
    model: res.model,
    parameters: res.parameters ?? {},
    exclusiveGroups: res.exclusive_groups ?? [],
    defaultsSource: res.defaults_source ?? 'unknown',
    recommendProviderDefaults: res.recommend_provider_defaults,
    samplingPresets: (res.sampling_presets ?? []).map((preset) => ({
      id: preset.id,
      temperature: preset.temperature,
      topP: preset.top_p,
    })),
    verbosity: {
      supported: res.verbosity?.supported ?? false,
      choices: res.verbosity?.choices ?? [],
      default: res.verbosity?.default,
    },
    output: {
      omissionSupported: res.output?.omission_supported ?? true,
      countsReasoningTokens: res.output?.counts_reasoning_tokens ?? false,
      recommended: res.output?.recommended,
    },
  }
}

export async function testModelConnection(
  token: string,
  payload: { profileId?: string; provider?: string; modelName?: string; baseUrl?: string },
): Promise<{
  ok: boolean
  provider: string
  modelName: string
  response: string
  latencyMs: number
  usage: { promptTokens?: number; completionTokens?: number; totalTokens?: number }
}> {
  const res = await requestJson<{
    ok: boolean
    provider: string
    model_name: string
    response: string
    latency_ms: number
    usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
  }>('/api/models/test-connection', {
    method: 'POST',
    token,
    body: JSON.stringify({
      profile_id: payload.profileId,
      provider: payload.provider,
      model_name: payload.modelName,
      base_url: payload.baseUrl,
    }),
  })
  return {
    ok: res.ok,
    provider: res.provider,
    modelName: res.model_name,
    response: res.response,
    latencyMs: res.latency_ms,
    usage: {
      promptTokens: res.usage?.prompt_tokens,
      completionTokens: res.usage?.completion_tokens,
      totalTokens: res.usage?.total_tokens,
    },
  }
}

export async function createModelProfile(
  token: string,
  payload: {
    profileId: string
    modelName: string
    provider: string
    baseUrl?: string
    samplingMode: 'provider_default' | 'stable' | 'flexible' | 'custom'
    outputMode: 'provider_default' | 'custom_limit'
    verbosity: 'low' | 'medium' | 'high' | null
    temperature?: number
    topP?: number
    topK?: number
    maxOutputTokens?: number
  },
): Promise<void> {
  await requestJson<void>('/api/models/profiles', {
    method: 'POST',
    token,
    body: JSON.stringify({
      profile_id: payload.profileId,
      provider: payload.provider,
      model_name: payload.modelName,
      base_url: payload.baseUrl,
      sampling_mode: payload.samplingMode,
      output_mode: payload.outputMode,
      verbosity: payload.verbosity,
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

export async function fetchModelProviders(token: string): Promise<string[]> {
  const res = await requestJson<{ items: Array<{ id: string }> }>('/api/models/providers', { token })
  return res.items.map((item) => item.id).filter(Boolean)
}

export async function createModelProvider(
  token: string,
  payload: { id: string; displayName: string; baseUrl: string; apiKeyEnv: string },
): Promise<void> {
  await requestJson('/api/models/providers', {
    method: 'POST',
    token,
    body: JSON.stringify({
      id: payload.id,
      display_name: payload.displayName,
      protocol: 'openai_chat',
      base_url: payload.baseUrl,
      api_key_env: payload.apiKeyEnv,
    }),
  })
}

export async function fetchProviderModels(
  token: string,
  params: { provider: string; q?: string; profileId?: string },
): Promise<string[]> {
  const search = new URLSearchParams()
  search.set('provider', params.provider)
  if (params?.q) search.set('q', params.q)
  if (params?.profileId) search.set('profile_id', params.profileId)
  const query = search.toString()
  const res = await requestJson<{ items: string[] }>(`/api/models/catalog?${query}`, { token })
  return res.items
}

/** @deprecated Use fetchProviderModels. */
export async function fetchAliyunModels(token: string, params?: { q?: string }): Promise<string[]> {
  return fetchProviderModels(token, { provider: 'aliyun', q: params?.q })
}

/** @deprecated Use fetchProviderModels. */
export async function fetchGeminiModels(token: string, params?: { q?: string }): Promise<string[]> {
  return fetchProviderModels(token, { provider: 'gemini', q: params?.q })
}
