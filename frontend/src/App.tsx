import { useEffect, useRef, useState } from 'react'
import './App.css'
import { appCards as mockApps, sessions as mockSessions } from './data/mockData'
import {
  activateSession,
  archiveSession,
  adminResetUserPassword,
  createModelProfile,
  createModelProvider,
  createSession,
  changeMyPassword,
  deleteModelProfile,
  deleteSession,
  deleteUser,
  fetchApps,
  adminCreateUser,
  fetchUsers,
  fetchModelProviders,
  fetchModelCapabilities,
  fetchProviderModels,
  fetchModelProfiles,
  fetchMe,
  fetchArtifacts,
  setDefaultModelProfile,
  fetchSessionMessages,
  fetchSessionRecords,
  fetchSBCEventSelection,
  fetchSessions,
  fetchSkills,
  fetchTools,
  login,
  register,
  logout,
  sendSessionMessage,
  selectSBCEvent,
  subscribeSessionEvents,
  stopSession,
  testModelConnection,
  updateToolEnabled,
  updateSkillMarkdown,
  updateModelProfile,
  type UserAccount,
} from './api/service'
import type { ArtifactItem, ModelProfile, RecordType, Role, SBCSelectionRequest, SessionGroups, SessionItem, SessionMessage, SessionRecord, SessionStatus, SkillItem, ToolItem, ViewKey } from './types/app'
import { Sidebar } from './components/layout/Sidebar'
import { Topbar } from './components/layout/Topbar'
import { SessionView } from './views/SessionView'
import { AppsView } from './views/AppsView'
import { NewSessionView } from './views/NewSessionView'
import { SkillsView } from './views/SkillsView'
import { ToolsView } from './views/ToolsView'
import { ResultsView } from './views/ResultsView'
import { ModelsView } from './views/ModelsView'
import { UserSettingsView } from './views/UserSettingsView'
import { ArchivedSessionsView } from './views/ArchivedSessionsView'
import { UsersView } from './views/UsersView'

function getErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'message' in error && typeof error.message === 'string') {
    return error.message
  }
  return '请求失败，请稍后重试'
}

function firstSession(groups: SessionGroups): SessionItem | null {
  return groups.active[0] ?? null
}

const AUTH_STORAGE_KEY = 'troubleshooting_agent_auth_v1'
const VIEW_STORAGE_KEY = 'troubleshooting_agent_view_v1'

type StoredAuth = {
  token: string
  username: string
  role: Role
  expiresAt: string
}

function saveAuth(auth: StoredAuth): void {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth))
}

function clearAuth(): void {
  localStorage.removeItem(AUTH_STORAGE_KEY)
}

function readAuth(): StoredAuth | null {
  const raw = localStorage.getItem(AUTH_STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<StoredAuth>
    if (!parsed.token || !parsed.username || !parsed.role || !parsed.expiresAt) return null
    return {
      token: parsed.token,
      username: parsed.username,
      role: parsed.role,
      expiresAt: parsed.expiresAt,
    }
  } catch {
    return null
  }
}

function readStoredView(): ViewKey | null {
  const raw = localStorage.getItem(VIEW_STORAGE_KEY)
  if (
    raw === 'session' ||
    raw === 'apps' ||
    raw === 'newSession' ||
    raw === 'archivedSessions' ||
    raw === 'skills' ||
    raw === 'tools' ||
    raw === 'results' ||
    raw === 'models' ||
    raw === 'users' ||
    raw === 'userSettings'
  ) {
    return raw
  }
  return null
}

function saveStoredView(view: ViewKey): void {
  localStorage.setItem(VIEW_STORAGE_KEY, view)
}

function normalizeViewForRole(view: ViewKey, role: Role): ViewKey {
  if (view === 'models' || view === 'users') {
    return role === 'admin' || role === 'super_admin' ? view : 'session'
  }
  return view
}

function isExpired(expiresAt: string): boolean {
  const ts = Date.parse(expiresAt)
  if (Number.isNaN(ts)) return true
  return ts <= Date.now()
}

function App() {
  const [loggedIn, setLoggedIn] = useState(false)
  const [token, setToken] = useState('')
  const [username, setUsername] = useState('demo_user')
  const [password, setPassword] = useState('123456')
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [registerPassword, setRegisterPassword] = useState('')
  const [registerConfirmPassword, setRegisterConfirmPassword] = useState('')
  const [authLoading, setAuthLoading] = useState(false)
  const [authError, setAuthError] = useState('')
  const [restoringAuth, setRestoringAuth] = useState(true)
  const [role, setRole] = useState<Role>('user')
  const [currentView, setCurrentView] = useState<ViewKey>(() => readStoredView() ?? 'session')
  const [selectedApp, setSelectedApp] = useState('fault_diagnoses')
  const [newSessionTitle, setNewSessionTitle] = useState('')
  const [selectedModelProfile, setSelectedModelProfile] = useState('gemini_default')
  const [defaultModelProfileId, setDefaultModelProfileId] = useState('')
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState('')
  const [providerModelCatalog, setProviderModelCatalog] = useState<string[]>([])
  const [modelProviders, setModelProviders] = useState<string[]>(['aliyun', 'gemini', 'openai'])
  const [catalogQuery, setCatalogQuery] = useState('')
  const [catalogProvider, setCatalogProvider] = useState('aliyun')
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [showToast, setShowToast] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const [copiedText, setCopiedText] = useState('')
  const [isResponding, setIsResponding] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [apps, setApps] = useState(mockApps)
  const [sessionGroups, setSessionGroups] = useState<SessionGroups>(mockSessions)
  const [currentSession, setCurrentSession] = useState<SessionItem | null>(firstSession(mockSessions))
  const [sessionMessages, setSessionMessages] = useState<SessionMessage[]>([])
  const [sessionRecords, setSessionRecords] = useState<SessionRecord[]>([])
  const [sessionArtifacts, setSessionArtifacts] = useState<ArtifactItem[]>([])
  const [sbcSelectionRequest, setSbcSelectionRequest] = useState<SBCSelectionRequest | null>(null)
  const currentSessionIdRef = useRef<string | null>(null)
  currentSessionIdRef.current = currentSession?.id ?? null
  const [sessionLoading, setSessionLoading] = useState(false)
  const [sessionError, setSessionError] = useState('')
  const [recordFilter, setRecordFilter] = useState<'all' | 'skills' | 'tools'>('all')
  const [artifactFilter, setArtifactFilter] = useState<'all' | 'doc' | 'image' | 'data'>('all')
  const [creatingSession, setCreatingSession] = useState(false)
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [selectedSkillId, setSelectedSkillId] = useState('')
  const [skillMarkdown, setSkillMarkdown] = useState('')
  const [skillsLoading, setSkillsLoading] = useState(false)
  const [skillsError, setSkillsError] = useState('')
  const [tools, setTools] = useState<ToolItem[]>([])
  const [toolsLoading, setToolsLoading] = useState(false)
  const [toolsError, setToolsError] = useState('')
  const [resultsFilter, setResultsFilter] = useState<'all' | 'doc' | 'image' | 'data'>('all')
  const [resultsSessionId, setResultsSessionId] = useState('')
  const [resultsArtifacts, setResultsArtifacts] = useState<ArtifactItem[]>([])
  const [resultsLoading, setResultsLoading] = useState(false)
  const [resultsError, setResultsError] = useState('')
  const [users, setUsers] = useState<UserAccount[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [usersError, setUsersError] = useState('')
  const [topSuccessBanner, setTopSuccessBanner] = useState('')
  const canManageUsers = role === 'admin' || role === 'super_admin'
  const canManageModels = role === 'admin' || role === 'super_admin'
  const eventSourceRef = useRef<(() => void) | null>(null)

  const statusText: Record<SessionStatus, string> = {
    active: '活跃（运行中）',
    archived: '归档',
  }
  const sessionForLayout: SessionItem = currentSession ?? {
    id: 'no_session',
    name: '暂无 Session',
    status: 'archived',
    updated: '--',
  }

  const switchView = (view: ViewKey) => {
    const nextView = normalizeViewForRole(view, role)
    setCurrentView(nextView)
    saveStoredView(nextView)
  }

  const closeEventStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current()
      eventSourceRef.current = null
    }
  }

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedText(text)
      window.setTimeout(() => setCopiedText(''), 1200)
    } catch {
      setCopiedText('')
    }
  }

  const applyModelProfiles = (data: { items: ModelProfile[]; defaultProfile: string }) => {
    setModelProfiles(data.items)
    setDefaultModelProfileId(data.defaultProfile)
    setSelectedModelProfile((prev) => {
      if (data.items.some((item) => item.id === prev)) return prev
      if (data.defaultProfile && data.items.some((item) => item.id === data.defaultProfile)) return data.defaultProfile
      return data.items[0]?.id ?? ''
    })
  }

  const loadBootstrap = async (authToken: string) => {
    const [appsData, sessionsData, skillsData, modelProfilesData, modelProvidersData, toolsData] = await Promise.all([
      fetchApps(authToken),
      fetchSessions(authToken),
      fetchSkills(authToken),
      fetchModelProfiles(authToken),
      fetchModelProviders(authToken),
      fetchTools(authToken),
    ])
    setApps(appsData.length ? appsData : mockApps)
    setSessionGroups(sessionsData)
    const preferredSession = firstSession(sessionsData)
    setCurrentSession(preferredSession)
    setSelectedApp(appsData[0]?.id ?? mockApps[0].id)
    applyModelProfiles(modelProfilesData)
    if (modelProvidersData.length) setModelProviders(modelProvidersData)
    setSkills(skillsData)
    if (skillsData[0]) {
      setSelectedSkillId(skillsData[0].id)
      setSkillMarkdown(skillsData[0].markdown)
    }
    setTools(toolsData)
  }

  const refreshModelProfiles = async () => {
    if (!token) return
    const latest = await fetchModelProfiles(token)
    applyModelProfiles(latest)
  }

  const loadSessionData = async (
    authToken: string,
    sessionId: string,
    nextRecordFilter: 'all' | 'skills' | 'tools',
    nextArtifactFilter: 'all' | 'doc' | 'image' | 'data',
    silent = false,
  ) => {
    if (!silent) setSessionLoading(true)
    setSessionError('')
    try {
      const [messages, records, artifacts, selection] = await Promise.all([
        fetchSessionMessages(authToken, sessionId),
        fetchSessionRecords(authToken, sessionId, nextRecordFilter),
        fetchArtifacts(authToken, { sessionId, type: nextArtifactFilter }),
        fetchSBCEventSelection(authToken, sessionId),
      ])
      if (currentSessionIdRef.current !== sessionId) return
      setSessionMessages(messages)
      setSessionRecords(records)
      setSessionArtifacts(artifacts)
      setSbcSelectionRequest(selection)
    } catch (error) {
      if (currentSessionIdRef.current !== sessionId) return
      setSessionError(getErrorMessage(error))
      setSessionMessages([])
      setSessionRecords([])
      setSessionArtifacts([])
      setSbcSelectionRequest(null)
    } finally {
      if (!silent) setSessionLoading(false)
    }
  }

  const runResultsSearch = async (authToken: string, nextFilter: 'all' | 'doc' | 'image' | 'data', nextSessionId: string) => {
    setResultsLoading(true)
    setResultsError('')
    try {
      const data = await fetchArtifacts(authToken, {
        type: nextFilter,
        sessionId: nextSessionId.trim() || undefined,
      })
      setResultsArtifacts(data)
    } catch (error) {
      setResultsError(getErrorMessage(error))
      setResultsArtifacts([])
    } finally {
      setResultsLoading(false)
    }
  }

  const loadUsers = async (authToken: string) => {
    setUsersLoading(true)
    setUsersError('')
    try {
      const items = await fetchUsers(authToken)
      setUsers(items)
    } catch (error) {
      setUsersError(getErrorMessage(error))
      setUsers([])
    } finally {
      setUsersLoading(false)
    }
  }

  const refreshTools = async (authToken: string) => {
    setToolsLoading(true)
    setToolsError('')
    try {
      setTools(await fetchTools(authToken))
    } catch (error) {
      setToolsError(getErrorMessage(error))
    } finally {
      setToolsLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const stored = readAuth()
      if (!stored || isExpired(stored.expiresAt)) {
        clearAuth()
        if (!cancelled) setRestoringAuth(false)
        return
      }
      try {
        const me = await fetchMe(stored.token)
        if (!cancelled) {
          setToken(stored.token)
          setRole(me.role)
          setUsername(me.username)
          await loadBootstrap(stored.token)
          setCurrentView(normalizeViewForRole(readStoredView() ?? 'session', me.role))
          setLoggedIn(true)
        }
      } catch {
        clearAuth()
      } finally {
        if (!cancelled) setRestoringAuth(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    closeEventStream()
    setIsResponding(false)
  }, [currentSession?.id])

  useEffect(() => {
    if (!loggedIn || !token || !currentSession) return
    void loadSessionData(token, currentSession.id, recordFilter, artifactFilter)
  }, [loggedIn, token, currentSession, recordFilter, artifactFilter])

  useEffect(() => {
    const selectedSkill = skills.find((item) => item.id === selectedSkillId)
    if (selectedSkill) {
      setSkillMarkdown(selectedSkill.markdown)
    }
  }, [selectedSkillId, skills])

  useEffect(() => {
    if (!loggedIn || !token) return
    void runResultsSearch(token, resultsFilter, resultsSessionId)
  }, [loggedIn, token, resultsFilter, resultsSessionId])

  useEffect(() => {
    if (!loggedIn || !token || !canManageModels) return
    let cancelled = false
    void (async () => {
      setCatalogLoading(true)
      setProviderModelCatalog([])
      try {
        const items = await fetchProviderModels(token, {
          provider: catalogProvider,
          q: catalogQuery,
        })
        if (!cancelled) {
          setProviderModelCatalog(items)
          setModelsError('')
        }
      } catch (error) {
        if (!cancelled) {
          setProviderModelCatalog([])
          setModelsError(getErrorMessage(error))
        }
      } finally {
        if (!cancelled) setCatalogLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loggedIn, token, canManageModels, catalogProvider, catalogQuery])

  useEffect(() => {
    if (!loggedIn || !token || !canManageUsers || currentView !== 'users') return
    void loadUsers(token)
  }, [loggedIn, token, canManageUsers, currentView])

  useEffect(() => {
    if (!loggedIn || !token || currentView !== 'tools') return
    void refreshTools(token)
  }, [loggedIn, token, currentView])

  useEffect(() => () => closeEventStream(), [])

  useEffect(() => {
    if (!topSuccessBanner) return
    const timer = window.setTimeout(() => {
      setTopSuccessBanner('')
    }, 3000)
    return () => {
      window.clearTimeout(timer)
    }
  }, [topSuccessBanner])

  const subscribeToSessionRun = (
    sentSessionId: string,
    runId: string,
    modelName?: string,
  ) => {
    closeEventStream()
    const upsertMessage = (message: SessionMessage) => {
      setSessionMessages((prev) => {
        const idx = prev.findIndex((item) => item.id === message.id)
        if (idx >= 0) {
          const next = [...prev]
          next[idx] = message
          return next
        }
        return [...prev, message]
      })
    }
    const appendLogMessage = (content: string, idSuffix: string) => {
      const messageId = `evt_${runId}_${idSuffix}`
      upsertMessage({
        id: messageId,
        role: 'assistant',
        content,
        kind: 'log',
      })
    }
    eventSourceRef.current = subscribeSessionEvents({
      token,
      sessionId: sentSessionId,
      runId,
      onEvent: (event) => {
        if (
          event.session_id !== sentSessionId ||
          currentSessionIdRef.current !== sentSessionId
        ) return
        if (event.type === 'run.accepted') {
          appendLogMessage('已接收请求，开始执行。', event.id)
          return
        }
        if (event.type === 'sbc.selection.requested') {
          setSbcSelectionRequest(event.payload as unknown as SBCSelectionRequest)
          return
        }
        if (event.type === 'sbc.selection.resumed') {
          setSbcSelectionRequest(null)
          return
        }
        if (event.type === 'message.delta') {
          const payloadMessage = event.payload.message
          if (
            payloadMessage &&
            typeof payloadMessage === 'object' &&
            'message_id' in payloadMessage &&
            'role' in payloadMessage &&
            'content' in payloadMessage
          ) {
            const raw = payloadMessage as {
              message_id: string
              role: SessionMessage['role']
              content: string
              kind?: SessionMessage['kind']
              model_profile_id?: string
              usage?: { total_tokens?: number }
              round_summary?: { model_calls?: number; total_tokens?: number }
            }
            upsertMessage({
              id: raw.message_id,
              role: raw.role,
              content: raw.content,
              kind: raw.kind ?? 'text',
              model: raw.model_profile_id,
              tokens: raw.usage?.total_tokens,
              roundSummary: raw.round_summary
                ? {
                    modelCalls: raw.round_summary.model_calls ?? 0,
                    totalTokens: raw.round_summary.total_tokens ?? 0,
                  }
                : undefined,
            })
          }
          return
        }
        if (event.type === 'tool.call') {
          const toolName = typeof event.payload.name === 'string' ? event.payload.name : 'unknown'
          appendLogMessage(`[tool call] ${toolName}() requested`, event.id)
          return
        }
        if (event.type === 'tool.result') {
          const toolName = typeof event.payload.name === 'string' ? event.payload.name : 'unknown'
          const toolStatus = typeof event.payload.status === 'string' ? event.payload.status : 'ok'
          appendLogMessage(`[tool result] ${toolName}() => ${toolStatus}`, event.id)
          return
        }
        if (event.type === 'record.created') {
          const recId = typeof event.payload.record_id === 'string' ? event.payload.record_id : String(event.payload.record_id ?? '')
          const rawType = typeof event.payload.record_type === 'string' ? event.payload.record_type : 'tool'
          const recType: RecordType = rawType === 'skill' ? 'skill' : rawType === 'tool' ? 'tool' : 'other'
          const recLabel = typeof event.payload.label === 'string' ? event.payload.label : ''
          const sourceKindRaw = typeof event.payload.source_kind === 'string' ? event.payload.source_kind : ''
          const sourceKind = sourceKindRaw === 'file' || sourceKindRaw === 'skill' || sourceKindRaw === 'other' ? sourceKindRaw : undefined
          const sourceName = typeof event.payload.source_name === 'string' ? event.payload.source_name : undefined
          const sourcePath = typeof event.payload.source_path === 'string' ? event.payload.source_path : undefined
          if (recId) {
            setSessionRecords((prev) => {
              if (prev.some((r) => r.id === recId)) return prev
              return [...prev, { id: recId, type: recType, label: recLabel, sourceKind, sourceName, sourcePath }]
            })
          }
          return
        }
        if (event.type === 'artifact.created') {
          if (
            typeof event.payload.artifact_id === 'string' &&
            typeof event.payload.filename === 'string' &&
            typeof event.payload.path === 'string' &&
            typeof event.payload.artifact_type === 'string'
          ) {
            const artifactId = event.payload.artifact_id
            const artifactFilename = event.payload.filename
            const artifactPath = event.payload.path
            const artifactTypeRaw = event.payload.artifact_type
            setSessionArtifacts((prev) => {
              const exists = prev.some((item) => item.id === artifactId)
              if (exists) return prev
              return [
                ...prev,
                {
                  id: artifactId,
                  name: artifactFilename,
                  path: artifactPath,
                  artifactType:
                    artifactTypeRaw === 'document'
                      ? 'document'
                      : artifactTypeRaw === 'image'
                        ? 'image'
                        : artifactTypeRaw === 'data'
                          ? 'data'
                          : 'other',
                  sessionId: sentSessionId,
                },
              ]
            })
          }
          return
        }
        if (event.type === 'run.done') {
          closeEventStream()
          setIsResponding(false)
          void refreshSessionsAndKeepSelection(sentSessionId)
          void loadSessionData(token, sentSessionId, recordFilter, artifactFilter, true)
          return
        }
        if (event.type === 'run.error') {
          const message = typeof event.payload.message === 'string' ? event.payload.message : '会话执行失败'
          const messageId =
            typeof event.payload.message_id === 'string'
              ? event.payload.message_id
              : `evt_${runId}_${event.id}`
          upsertMessage({
            id: messageId,
            role: 'assistant',
            content: message,
            kind: 'error',
            model: modelName,
          })
          closeEventStream()
          setIsResponding(false)
          void loadSessionData(token, sentSessionId, recordFilter, artifactFilter, true)
        }
      },
      onError: (message) => {
        setSessionError(message)
        closeEventStream()
        setIsResponding(false)
      },
    })
  }

  useEffect(() => {
    if (
      !loggedIn ||
      !currentSession ||
      currentSession.runStatus !== 'running' ||
      !currentSession.activeRunId
    ) return
    setIsResponding(true)
    subscribeToSessionRun(
      currentSession.id,
      currentSession.activeRunId,
      currentSession.model,
    )
  }, [
    loggedIn,
    currentSession?.id,
    currentSession?.runStatus,
    currentSession?.activeRunId,
  ])

  const handleSendOrStop = async () => {
    if (!currentSession) return
    if (isResponding) {
      closeEventStream()
      try {
        await stopSession(token, currentSession.id)
      } catch (error) {
        setSessionError(getErrorMessage(error))
      } finally {
        setIsResponding(false)
      }
      return
    }
    if (!chatInput.trim()) return
    setIsResponding(true)
    setSessionError('')
    const nextMessage = chatInput.trim()
    const optimisticId = `local_u_${Date.now()}`
    setSessionMessages((prev) => [...prev, { id: optimisticId, role: 'user', content: nextMessage, kind: 'text' }])
    setChatInput('')
    try {
      const sentSessionId = currentSession.id
      const response = await sendSessionMessage(token, sentSessionId, nextMessage)
      subscribeToSessionRun(sentSessionId, response.run_id, currentSession.model)
    } catch (error) {
      setSessionError(getErrorMessage(error))
      setIsResponding(false)
    }
  }

  const handleSelectSBCEvent = async (eventId: string) => {
    if (!currentSession || isResponding) return
    setIsResponding(true)
    setSessionError('')
    const content = `选择中断事件 ${eventId} 继续排查`
    setSessionMessages((prev) => [
      ...prev,
      {
        id: `local_u_${Date.now()}`,
        role: 'user',
        content,
        kind: 'text',
      },
    ])
    try {
      const sentSessionId = currentSession.id
      const response = await selectSBCEvent(token, sentSessionId, eventId)
      if (currentSessionIdRef.current !== sentSessionId) return
      setSbcSelectionRequest(null)
      subscribeToSessionRun(sentSessionId, response.run_id, currentSession.model)
    } catch (error) {
      if (currentSessionIdRef.current !== currentSession.id) return
      setSessionError(getErrorMessage(error))
      setIsResponding(false)
      void loadSessionData(
        token,
        currentSession.id,
        recordFilter,
        artifactFilter,
        true,
      )
    }
  }

  const refreshSessionsAndKeepSelection = async (preferredSessionId?: string) => {
    const sessionsData = await fetchSessions(token)
    setSessionGroups(sessionsData)
    const candidateId = preferredSessionId ?? currentSession?.id
    const matched = candidateId ? sessionsData.active.find((item) => item.id === candidateId) ?? null : null
    const next = matched ?? firstSession(sessionsData)
    setCurrentSession(next)
    return next
  }

  const handleArchiveSession = async (session: SessionItem) => {
    try {
      await archiveSession(token, session.id)
      await refreshSessionsAndKeepSelection(session.id)
    } catch (error) {
      setSessionError(getErrorMessage(error))
    }
  }

  const handleDeleteSession = async (session: SessionItem) => {
    try {
      await deleteSession(token, session.id)
      await refreshSessionsAndKeepSelection(undefined)
      if (currentSession?.id === session.id) {
        setSessionMessages([])
        setSessionRecords([])
        setSessionArtifacts([])
      }
    } catch (error) {
      setSessionError(getErrorMessage(error))
    }
  }

  const handleActivateSession = async (session: SessionItem) => {
    try {
      await activateSession(token, session.id)
      await refreshSessionsAndKeepSelection(session.id)
      switchView('session')
    } catch (error) {
      setSessionError(getErrorMessage(error))
    }
  }

  const resetAfterLogout = () => {
    setLoggedIn(false)
    setToken('')
    setApps(mockApps)
    setSessionGroups(mockSessions)
    setCurrentSession(firstSession(mockSessions))
    setAuthMode('login')
    setPassword('')
    setRegisterPassword('')
    setRegisterConfirmPassword('')
    setTools([])
    setToolsError('')
    setUsers([])
    setUsersError('')
    setTopSuccessBanner('')
  }

  const handleLogin = async () => {
    setAuthLoading(true)
    setAuthError('')
    try {
      const loginRes = await login({ username, password })
      const expiresAt = loginRes.expires_at ?? new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
      saveAuth({
        token: loginRes.access_token,
        username: username.trim(),
        role: loginRes.role,
        expiresAt,
      })
      setToken(loginRes.access_token)
      setRole(loginRes.role)
      await loadBootstrap(loginRes.access_token)
      setCurrentView(normalizeViewForRole(readStoredView() ?? 'session', loginRes.role))
      setLoggedIn(true)
    } catch (error) {
      setAuthError(getErrorMessage(error))
    } finally {
      setAuthLoading(false)
    }
  }

  const handleRegister = async () => {
    setAuthLoading(true)
    setAuthError('')
    try {
      const cleanUsername = username.trim()
      if (!cleanUsername) {
        throw new Error('用户名不能为空')
      }
      if (registerPassword.length < 6) {
        throw new Error('密码长度至少为 6 位')
      }
      if (registerPassword !== registerConfirmPassword) {
        throw new Error('两次输入的密码不一致')
      }
      await register({ username: cleanUsername, password: registerPassword })
      setPassword(registerPassword)
      setAuthMode('login')
      setAuthError('注册成功，请登录')
    } catch (error) {
      setAuthError(getErrorMessage(error))
    } finally {
      setAuthLoading(false)
    }
  }

  return (
    <div className="root">
      {!loggedIn && (
        <div className="login">
          <div className="card">
            <h1 className="title">troubleshooting_agent</h1>
            <p className="sub">前端联调版（API）</p>
            {restoringAuth && <div className="muted">正在恢复登录状态...</div>}
            {!restoringAuth && (
              <>
                <div className="authTabs">
                  <button type="button" className={authMode === 'login' ? 'primary' : ''} onClick={() => setAuthMode('login')}>
                    登录
                  </button>
                  <button type="button" className={authMode === 'register' ? 'primary' : ''} onClick={() => setAuthMode('register')}>
                    注册
                  </button>
                </div>
                {authMode === 'login' && (
                  <form
                    autoComplete="on"
                    onSubmit={(event) => {
                      event.preventDefault()
                      void handleLogin()
                    }}
                  >
                    <input
                      name="username"
                      autoComplete="username"
                      value={username}
                      placeholder="用户名（3-32位）"
                      onChange={(e) => setUsername(e.target.value)}
                    />
                    <input
                      name="password"
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      placeholder="密码"
                      onChange={(e) => setPassword(e.target.value)}
                    />
                    {authError && <div className="errorText">{authError}</div>}
                    <button
                      className="primary"
                      type="submit"
                      disabled={restoringAuth || authLoading || !username.trim() || !password.trim()}
                    >
                      {authLoading ? '登录中...' : '登录进入'}
                    </button>
                  </form>
                )}
                {authMode === 'register' && (
                  <form
                    autoComplete="on"
                    onSubmit={(event) => {
                      event.preventDefault()
                      void handleRegister()
                    }}
                  >
                    <input
                      name="username"
                      autoComplete="username"
                      value={username}
                      placeholder="用户名（3-32位）"
                      onChange={(e) => setUsername(e.target.value)}
                    />
                    <input
                      name="new_password"
                      type="password"
                      autoComplete="new-password"
                      value={registerPassword}
                      placeholder="密码（至少6位）"
                      onChange={(e) => setRegisterPassword(e.target.value)}
                    />
                    <input
                      name="confirm_password"
                      type="password"
                      autoComplete="new-password"
                      value={registerConfirmPassword}
                      placeholder="确认密码"
                      onChange={(e) => setRegisterConfirmPassword(e.target.value)}
                    />
                    {authError && <div className="errorText">{authError}</div>}
                    <button
                      className="primary"
                      type="submit"
                      disabled={restoringAuth || authLoading || !username.trim() || !registerPassword.trim() || !registerConfirmPassword.trim()}
                    >
                      {authLoading ? '注册中...' : '注册账号'}
                    </button>
                  </form>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {loggedIn && (
        <div className="layout">
          <Sidebar
            sessions={sessionGroups}
            currentSession={sessionForLayout}
            currentView={currentView}
            onSelectSession={(session) => {
              if (session.status !== 'active') return
              setCurrentSession(session)
              switchView('session')
            }}
            onArchiveSession={(session) => void handleArchiveSession(session)}
            onActivateSession={(session) => void handleActivateSession(session)}
            onDeleteSession={(session) => void handleDeleteSession(session)}
            onSwitchView={switchView}
            role={role}
          />

          <main className="main">
            <Topbar
              currentView={currentView}
              currentSessionName={sessionForLayout.name}
              role={role}
              username={username}
              userMenuOpen={userMenuOpen}
              onToggleUserMenu={() => setUserMenuOpen((v) => !v)}
              onOpenUserSettings={() => {
                setUserMenuOpen(false)
                switchView('userSettings')
              }}
              onLogout={() => {
                setUserMenuOpen(false)
                void (async () => {
                  closeEventStream()
                  try {
                    await logout(token)
                  } catch (error) {
                    setAuthError(`登出接口失败：${getErrorMessage(error)}`)
                  } finally {
                    clearAuth()
                    resetAfterLogout()
                  }
                })()
              }}
              onBackSession={() => switchView('session')}
            />

            <div className={`content ${currentView === 'session' ? 'sessionContent' : ''}`}>
              {currentView === 'session' && currentSession && (
                <SessionView
                  token={token}
                  currentSession={currentSession}
                  statusText={statusText}
                  copiedText={copiedText}
                  onCopy={handleCopy}
                  messages={sessionMessages}
                  sbcSelectionRequest={sbcSelectionRequest}
                  onSelectSBCEvent={(eventId) => void handleSelectSBCEvent(eventId)}
                  records={sessionRecords}
                  artifacts={sessionArtifacts}
                  recordFilter={recordFilter}
                  artifactFilter={artifactFilter}
                  onChangeRecordFilter={setRecordFilter}
                  onChangeArtifactFilter={setArtifactFilter}
                  chatInput={chatInput}
                  onChatInputChange={setChatInput}
                  isResponding={isResponding}
                  onSendOrStop={() => void handleSendOrStop()}
                  onArchiveSession={() => {
                    if (!currentSession) return
                    void handleArchiveSession(currentSession)
                  }}
                  onDeleteSession={() => {
                    if (!currentSession) return
                    void handleDeleteSession(currentSession)
                  }}
                  loading={sessionLoading}
                  error={sessionError}
                />
              )}
              {currentView === 'session' && !currentSession && <div className="panel muted">暂无会话，请先创建新 Session。</div>}
              {currentView === 'apps' && (
                <AppsView
                  apps={apps}
                  onChoose={(appId) => {
                    setSelectedApp(appId)
                    switchView('newSession')
                  }}
                />
              )}
              {currentView === 'newSession' && (
                <NewSessionView
                  selectedApp={selectedApp}
                  onChangeApp={setSelectedApp}
                  sessionTitle={newSessionTitle}
                  onChangeSessionTitle={setNewSessionTitle}
                  apps={apps}
                  modelProfiles={modelProfiles}
                  selectedModelProfile={selectedModelProfile}
                  onChangeModelProfile={setSelectedModelProfile}
                  creating={creatingSession}
                  onCreate={() => {
                    void (async () => {
                      setCreatingSession(true)
                      try {
                        const created = await createSession(
                          token,
                          selectedApp,
                          selectedModelProfile,
                          newSessionTitle.trim() ? newSessionTitle.trim() : undefined,
                        )
                        const sessionsData = await fetchSessions(token)
                        setSessionGroups(sessionsData)
                        setCurrentSession(created)
                        setNewSessionTitle('')
                        switchView('session')
                      } catch (error) {
                        setSessionError(getErrorMessage(error))
                      } finally {
                        setCreatingSession(false)
                      }
                    })()
                  }}
                />
              )}
              {currentView === 'archivedSessions' && (
                <ArchivedSessionsView
                  items={sessionGroups.archived}
                  onActivate={(item) => void handleActivateSession(item)}
                  onDelete={(item) => void handleDeleteSession(item)}
                />
              )}
              {currentView === 'skills' && (
                <SkillsView
                  skills={skills}
                  selectedSkillId={selectedSkillId}
                  markdown={skillMarkdown}
                  onSelectSkill={setSelectedSkillId}
                  onChangeMarkdown={setSkillMarkdown}
                  onSaveVersion={() => {
                    void (async () => {
                      if (!selectedSkillId) return
                      setSkillsLoading(true)
                      setSkillsError('')
                      try {
                        await updateSkillMarkdown(token, selectedSkillId, skillMarkdown)
                        const latest = await fetchSkills(token)
                        setSkills(latest)
                        setShowToast(true)
                      } catch (error) {
                        setSkillsError(getErrorMessage(error))
                      } finally {
                        setSkillsLoading(false)
                      }
                    })()
                  }}
                  loading={skillsLoading}
                  error={skillsError}
                />
              )}
              {currentView === 'tools' && (
                <ToolsView
                  role={role}
                  tools={tools}
                  loading={toolsLoading}
                  error={toolsError}
                  onToggleEnabled={(tool, enabled) => {
                    if (!(role === 'admin' || role === 'super_admin')) return
                    void (async () => {
                      setToolsError('')
                      const snapshot = tools
                      setTools((prev) => prev.map((item) => (item.name === tool.name ? { ...item, enabled } : item)))
                      try {
                        const updated = await updateToolEnabled(token, tool.name, enabled)
                        setTools((prev) => prev.map((item) => (item.name === updated.name ? updated : item)))
                      } catch (error) {
                        setTools(snapshot)
                        setToolsError(getErrorMessage(error))
                      }
                    })()
                  }}
                />
              )}
              {currentView === 'results' && (
                <ResultsView
                  token={token}
                  artifacts={resultsArtifacts}
                  filter={resultsFilter}
                  searchSessionId={resultsSessionId}
                  onChangeFilter={setResultsFilter}
                  onChangeSearchSessionId={setResultsSessionId}
                  onSearch={() => void runResultsSearch(token, resultsFilter, resultsSessionId)}
                  loading={resultsLoading}
                  error={resultsError}
                />
              )}
              {currentView === 'models' && canManageModels && (
                <ModelsView
                  profiles={modelProfiles}
                  defaultProfileId={defaultModelProfileId}
                  providerModels={providerModelCatalog}
                  providers={modelProviders}
                  onCreateProvider={async (payload) => {
                    await createModelProvider(token, payload)
                    const latest = await fetchModelProviders(token)
                    setModelProviders(latest)
                    setCatalogProvider(payload.id.trim().toLowerCase())
                    setTopSuccessBanner('服务商连接创建成功')
                  }}
                  catalogQuery={catalogQuery}
                  onCatalogProviderChange={setCatalogProvider}
                  onCatalogQueryChange={setCatalogQuery}
                  catalogLoading={catalogLoading}
                  loading={modelsLoading}
                  error={modelsError}
                  onSave={(payload) => {
                    void (async () => {
                      setModelsLoading(true)
                      setModelsError('')
                      try {
                        await updateModelProfile(token, payload.profileId, {
                          samplingMode: payload.samplingMode,
                          outputMode: payload.outputMode,
                          verbosity: payload.verbosity,
                          temperature: payload.temperature,
                          topP: payload.topP,
                          topK: payload.topK,
                          maxOutputTokens: payload.maxOutputTokens,
                        })
                        await refreshModelProfiles()
                        setTopSuccessBanner('模型入口更新成功')
                      } catch (error) {
                        setModelsError(getErrorMessage(error))
                      } finally {
                        setModelsLoading(false)
                      }
                    })()
                  }}
                  onCreate={(payload) => {
                    void (async () => {
                      setModelsLoading(true)
                      setModelsError('')
                      try {
                        await createModelProfile(token, {
                          profileId: payload.profileId,
                          provider: payload.provider,
                          modelName: payload.modelName,
                          baseUrl: payload.baseUrl,
                          samplingMode: payload.samplingMode,
                          outputMode: payload.outputMode,
                          verbosity: payload.verbosity,
                          temperature: payload.temperature,
                          topP: payload.topP,
                          topK: payload.topK,
                          maxOutputTokens: payload.maxOutputTokens,
                        })
                        await refreshModelProfiles()
                        setSelectedModelProfile(payload.profileId)
                        setTopSuccessBanner('模型入口创建成功')
                      } catch (error) {
                        setModelsError(getErrorMessage(error))
                      } finally {
                        setModelsLoading(false)
                      }
                    })()
                  }}
                  onTestConnection={(payload) => testModelConnection(token, payload)}
                  onGetCapabilities={(payload) => fetchModelCapabilities(token, payload)}
                  onSetDefault={(profileId) => {
                    void (async () => {
                      setModelsLoading(true)
                      setModelsError('')
                      try {
                        await setDefaultModelProfile(token, profileId)
                        await refreshModelProfiles()
                        setSelectedModelProfile(profileId)
                        setTopSuccessBanner('默认模型入口已更新')
                      } catch (error) {
                        setModelsError(getErrorMessage(error))
                      } finally {
                        setModelsLoading(false)
                      }
                    })()
                  }}
                  onDelete={(profileId) => {
                    return (async () => {
                      setModelsLoading(true)
                      setModelsError('')
                      try {
                        await deleteModelProfile(token, profileId)
                        await refreshModelProfiles()
                        setTopSuccessBanner('模型入口已删除')
                        return true
                      } catch (error) {
                        setModelsError(getErrorMessage(error))
                        return false
                      } finally {
                        setModelsLoading(false)
                      }
                    })()
                  }}
                />
              )}
              {currentView === 'users' && canManageUsers && (
                <UsersView
                  users={users}
                  loading={usersLoading}
                  error={usersError}
                  currentRole={role}
                  currentUsername={username}
                  onRefresh={() => void loadUsers(token)}
                  onCreateUser={async (payload) => {
                    setUsersLoading(true)
                    setUsersError('')
                    try {
                      await adminCreateUser(token, payload)
                      await loadUsers(token)
                      setTopSuccessBanner('用户创建成功')
                    } catch (error) {
                      const message = getErrorMessage(error)
                      setUsersError(message)
                      throw new Error(message)
                    } finally {
                      setUsersLoading(false)
                    }
                  }}
                  onDeleteUser={async (targetUsername) => {
                    setUsersLoading(true)
                    setUsersError('')
                    try {
                      await deleteUser(token, targetUsername)
                      await loadUsers(token)
                      setTopSuccessBanner('用户删除成功')
                    } catch (error) {
                      const message = getErrorMessage(error)
                      setUsersError(message)
                      throw new Error(message)
                    } finally {
                      setUsersLoading(false)
                    }
                  }}
                  onResetPassword={async (payload) => {
                    setUsersLoading(true)
                    setUsersError('')
                    try {
                      await adminResetUserPassword(token, payload.username, { newPassword: payload.newPassword })
                      await loadUsers(token)
                      setTopSuccessBanner('用户密码重置成功')
                    } catch (error) {
                      const message = getErrorMessage(error)
                      setUsersError(message)
                      throw new Error(message)
                    } finally {
                      setUsersLoading(false)
                    }
                  }}
                />
              )}
              {currentView === 'userSettings' && (
                <UserSettingsView
                  role={role}
                  username={username}
                  onChangePassword={async (payload) => {
                    try {
                      await changeMyPassword(token, payload)
                      setTopSuccessBanner('密码修改成功')
                    } catch (error) {
                      throw new Error(getErrorMessage(error))
                    }
                  }}
                />
              )}
            </div>
          </main>
        </div>
      )}

      {topSuccessBanner && (
        <div className="topSuccessBanner" role="status" aria-live="polite">
          <span>{topSuccessBanner}</span>
          <button type="button" onClick={() => setTopSuccessBanner('')}>关闭</button>
        </div>
      )}

      {showToast && (
        <div className="toast">
          <div className="toastTitle">能力配置已更新</div>
          <div className="muted">是否刷新当前会话上下文？</div>
          <div className="row">
            <button className="primary" type="button" onClick={() => setShowToast(false)}>
              刷新并回到 Session
            </button>
            <button type="button" onClick={() => setShowToast(false)}>
              稍后处理
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
