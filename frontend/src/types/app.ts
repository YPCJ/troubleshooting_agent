export type Role = 'super_admin' | 'admin' | 'user'

export type SessionStatus = 'active' | 'archived'

export type ViewKey = 'session' | 'apps' | 'newSession' | 'archivedSessions' | 'skills' | 'tools' | 'results' | 'models' | 'users' | 'userSettings'

export type SessionItem = {
  id: string
  name: string
  status: SessionStatus
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
  kind?: 'text' | 'log'
  model?: string
  tokens?: number
}

export type RecordType = 'skill' | 'tool' | 'other'

export type SessionRecord = {
  id: string
  type: RecordType
  label: string
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

export type ModelProfile = {
  id: string
  provider: string
  modelName: string
  baseUrl?: string
  temperature?: number
  topP?: number
  topK?: number
  maxOutputTokens?: number
}
