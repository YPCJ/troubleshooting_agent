export type Role = 'super_admin' | 'admin' | 'user'

export type SessionStatus = 'active' | 'archived'

export type ViewKey = 'session' | 'apps' | 'newSession' | 'archivedSessions' | 'skills' | 'tools' | 'results' | 'models' | 'users' | 'userSettings'

export type SessionItem = {
  id: string
  name: string
  status: SessionStatus
  runStatus?: string
  activeRunId?: string
  updated: string
  model?: string
}

export type SessionGroups = {
  active: SessionItem[]
  archived: SessionItem[]
}

export type AppCard = {
  id: string
  icon: string
  desc: string
}

export type MessageRole = 'user' | 'assistant' | 'system'

export type SessionMessage = {
  id: string
  role: MessageRole
  content: string
  kind?: 'text' | 'log' | 'error'
  model?: string
  tokens?: number
  roundSummary?: {
    modelCalls: number
    totalTokens: number
  }
}

export type SBCInterruptionEvent = {
  event_id: string
  interruption_start_bdt: string
  interruption_end_bdt: string
  duration_seconds: number
  satellites: string[]
  satellite_count: number
  pattern: string
  landing_satellites: string[]
}

export type SBCSelectionRequest = {
  type: 'event_selection'
  prompt: string
  candidates: SBCInterruptionEvent[]
}

export type RecordType = 'skill' | 'tool' | 'other'

export type SessionRecord = {
  id: string
  type: RecordType
  label: string
  sourceKind?: 'file' | 'skill' | 'other'
  sourceName?: string
  sourcePath?: string
}

export type ArtifactType = 'document' | 'image' | 'data' | 'other'

export type ArtifactItem = {
  id: string
  name: string
  path: string
  artifactType: ArtifactType
  sessionId: string
}

export type SkillItem = {
  id: string
  markdown: string
}

export type ToolItem = {
  name: string
  description: string
  category: 'file' | 'shell' | 'data' | 'skills' | 'sbc' | 'other'
  enabled: boolean
  /** False when no implementation is bound, so the tool cannot run even if enabled. */
  available: boolean
  apps: string[]
}

export type ModelProfile = {
  id: string
  provider: string
  modelName: string
  baseUrl?: string
  samplingMode?: 'provider_default' | 'stable' | 'flexible' | 'custom'
  outputMode?: 'provider_default' | 'custom_limit'
  verbosity?: 'low' | 'medium' | 'high'
  temperature?: number
  topP?: number
  topK?: number
  maxOutputTokens?: number
}

export type ModelParameterCapability = {
  supported: boolean
  min?: number | null
  max?: number | null
  step?: number | null
  default?: number | null
}

export type ModelCapabilities = {
  provider: string
  model: string
  parameters: Partial<Record<'temperature' | 'top_p' | 'top_k' | 'max_output_tokens', ModelParameterCapability>>
  exclusiveGroups: string[][]
  defaultsSource: string
  recommendProviderDefaults?: boolean
  samplingPresets: Array<{
    id: 'stable' | 'flexible' | string
    temperature?: number
    topP?: number
  }>
  verbosity: {
    supported: boolean
    choices: Array<'low' | 'medium' | 'high' | string>
    default?: string | null
  }
  output: {
    omissionSupported: boolean
    countsReasoningTokens: boolean
    recommended?: number | null
  }
}
