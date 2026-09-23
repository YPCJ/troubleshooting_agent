import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ArtifactItem, SBCSelectionRequest, SessionItem, SessionMessage, SessionRecord, SessionStatus } from '../types/app'
import { fetchSessionPreview } from '../api/service'
import { ArtifactLink } from '../components/ArtifactLink'
import { MarkdownContent } from '../components/MarkdownContent'

type Props = {
  token: string
  currentSession: SessionItem
  statusText: Record<SessionStatus, string>
  copiedText: string
  onCopy: (text: string) => void
  messages: SessionMessage[]
  sbcSelectionRequest: SBCSelectionRequest | null
  onSelectSBCEvent: (eventId: string) => void
  records: SessionRecord[]
  artifacts: ArtifactItem[]
  recordFilter: 'all' | 'skills' | 'tools'
  artifactFilter: 'all' | 'doc' | 'image' | 'data'
  onChangeRecordFilter: (value: 'all' | 'skills' | 'tools') => void
  onChangeArtifactFilter: (value: 'all' | 'doc' | 'image' | 'data') => void
  chatInput: string
  onChatInputChange: (value: string) => void
  isResponding: boolean
  onSendOrStop: () => void
  onArchiveSession: () => void
  onDeleteSession: () => void
  loading: boolean
  error: string
}

const SBC_PATTERN_LABELS: Record<string, string> = {
  single_pass: '单圈次单星中断',
  single_sat_long: '单星长时间中断',
  fixed_landing_sat: '固定落地星批量中断',
  fixed_sat_batch: '一批卫星中断',
  multiple_sat_network: '多星网络中断',
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}秒`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = Math.round(seconds % 60)
  return [
    hours ? `${hours}小时` : '',
    minutes ? `${minutes}分` : '',
    remainder ? `${remainder}秒` : '',
  ].filter(Boolean).join('')
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <rect x="5" y="1.5" width="9" height="9" rx="1.8" />
      <rect x="2" y="5.5" width="9" height="9" rx="1.8" />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M2.2 10.2L16.8 3.2L13 16.8L9.2 11.2L2.2 10.2Z" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="7.2" />
      <rect x="7.1" y="7.1" width="5.8" height="5.8" rx="0.8" />
    </svg>
  )
}

function PreviewRenderedIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 4.2C5.6 4.2 2.7 8 2 10c0.7 2 3.6 5.8 8 5.8s7.3-3.8 8-5.8c-0.7-2-3.6-5.8-8-5.8Zm0 9.3a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7Z" />
      <circle cx="10" cy="10" r="1.8" />
    </svg>
  )
}

function PreviewSourceIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M6.2 6 2.6 10l3.6 4 1.3-1.2L5 10l2.5-2.8L6.2 6Zm7.6 0-1.3 1.2L15 10l-2.5 2.8 1.3 1.2 3.6-4-3.6-4ZM11.5 4 8 16h1.6L13 4h-1.5Z" />
    </svg>
  )
}

function RunningGridIcon() {
  return (
    <span className="runningGrid" aria-hidden="true">
      {Array.from({ length: 9 }).map((_, idx) => (
        <span key={idx} />
      ))}
    </span>
  )
}

type ToolCallEntry = {
  id: string
  name: string
  round: number | null
  argumentsText: string
  resultText: string
  record: SessionRecord | null
}

type CallGroup = {
  id: string
  calls: ToolCallEntry[]
}

type TodoStatus = 'pending' | 'in_progress' | 'completed'

type TodoItem = {
  id: string
  text: string
  status: TodoStatus
}

type TodoBoard = {
  items: TodoItem[]
}

type RenderEntry =
  | { type: 'message'; message: SessionMessage }
  | { type: 'callGroup'; group: CallGroup }

type PreviewData = {
  recordId: string
  sourceKind: 'file' | 'skill' | 'other'
  sourceName: string
  sourcePath: string
  title: string
  content: string
  contentKind: 'markdown' | 'text'
}

const SIDEBAR_WIDTH_STORAGE_KEY = 'sessionView.sidePaneWidth'
const SIDEBAR_MIN_WIDTH = 300
const SIDEBAR_MAX_WIDTH = 760
const CHAT_MIN_WIDTH = 420

function extractRound(line: string): number | null {
  const match = line.match(/第\s*(\d+)\s*次(?:模型)?调用/)
  return match ? Number(match[1]) : null
}

function extractToolName(line: string): string | null {
  const match = line.match(/\[tool call\]\s*([a-zA-Z0-9_-]+)\(\)\s*requested/)
  return match ? match[1] : null
}

function extractToolArguments(line: string): string | null {
  const prefix = '### 本次工具调用的参数：'
  return line.startsWith(prefix) ? line.slice(prefix.length).trim() : null
}

function toolArgument(call: ToolCallEntry, keys: string[]): string {
  try {
    const args = JSON.parse(call.argumentsText) as Record<string, unknown>
    for (const key of keys) {
      if (typeof args[key] === 'string') return args[key]
    }
  } catch {
    return ''
  }
  return ''
}

function pathName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}

function toolActionLabel(call: ToolCallEntry): string {
  if (call.record?.sourceKind === 'skill') return `加载 Skill：${displayRecordName(call.record)}`
  if (call.record?.sourceKind === 'file') return `读取文件：${displayRecordName(call.record)}`

  let subject = ''
  try {
    const args = JSON.parse(call.argumentsText) as Record<string, unknown>
    const candidate = args.command ?? args.query ?? args.path ?? args.name
    if (typeof candidate === 'string') subject = summarizeText(candidate, 68)
  } catch {
    subject = summarizeText(call.argumentsText, 68)
  }
  return subject ? `${call.name} · ${subject}` : call.name
}

function summarizeCallGroup(group: CallGroup): string {
  if (!group.calls.length) return '已完成问题分析'

  const actions = new Map<string, string>()
  const readFiles: string[] = []
  const writtenFiles: string[] = []
  const editedFiles: string[] = []
  const loadedSkills: string[] = []
  const addAction = (key: string, label: string) => {
    if (!actions.has(key)) actions.set(key, label)
  }
  const addUnique = (items: string[], value: string) => {
    if (value && !items.includes(value)) items.push(value)
  }

  for (const call of group.calls) {
    const sourceName = call.record ? displayRecordName(call.record) : ''
    if (call.name === 'load_skills' || call.record?.sourceKind === 'skill') {
      addUnique(loadedSkills, sourceName || toolArgument(call, ['name']))
      continue
    }
    if (call.name === 'read_file') {
      addUnique(readFiles, sourceName || pathName(toolArgument(call, ['path'])))
      continue
    }
    if (call.name === 'write_file') {
      addUnique(writtenFiles, sourceName || pathName(toolArgument(call, ['path'])))
      continue
    }
    if (call.name === 'edit_file') {
      addUnique(editedFiles, sourceName || pathName(toolArgument(call, ['path'])))
      continue
    }
    if (call.name === 'bash') {
      const command = call.argumentsText.toLowerCase()
      if (/\b(find|grep|rg)\b/.test(command)) addAction('search', '检索项目文件和代码引用')
      else if (/\bls\b/.test(command)) addAction('directory', '检查目录内容')
      else if (/\b(git)\b/.test(command)) addAction('git', '检查代码变更')
      else if (/(pytest|unittest|npm\s+(run\s+)?(test|build)|\btsc\b)/.test(command)) addAction('verify', '验证代码变更')
      else addAction('command', '执行必要的系统命令')
      continue
    }

    const knownActions: Record<string, string> = {
      data_query: '查询业务数据',
      read_csv: '读取并检查数据文件',
      todo: '更新任务执行进度',
      task: '执行专项子任务',
    }
    addAction(call.name, knownActions[call.name] ?? `使用 ${call.name} 完成处理`)
  }

  if (loadedSkills.length) {
    addAction('skills', `加载 ${loadedSkills.slice(0, 2).join('、') || '所需'} Skill`)
  }
  if (readFiles.length) {
    addAction('read-files', `查看 ${readFiles.slice(0, 2).join('、')}${readFiles.length > 2 ? ' 等文件' : ''}`)
  }
  if (writtenFiles.length) {
    addAction('write-files', `创建 ${writtenFiles.slice(0, 2).join('、')}${writtenFiles.length > 2 ? ' 等文件' : ''}`)
  }
  if (editedFiles.length) {
    addAction('edit-files', `修改 ${editedFiles.slice(0, 2).join('、')}${editedFiles.length > 2 ? ' 等文件' : ''}`)
  }

  const summaries = Array.from(actions.values()).slice(0, 3)
  if (summaries.length === 0) return '已完成问题分析'
  if (summaries.length === 1) return `已${summaries[0]}`
  return `已${summaries.slice(0, -1).join('、')}，并${summaries[summaries.length - 1]}`
}

function summarizeText(content: string, limit = 72): string {
  const singleLine = content.replace(/\s+/g, ' ').trim()
  if (!singleLine) return ''
  if (singleLine.length <= limit) return singleLine
  return `${singleLine.slice(0, limit)}…`
}

function extractTodoToolName(line: string): string | null {
  const direct = line.match(/本次工具调用：([a-zA-Z0-9_-]+)/)
  if (direct) return direct[1]
  const fallback = line.match(/\[tool call\]\s*([a-zA-Z0-9_-]+)\(\)\s*requested/)
  return fallback ? fallback[1] : null
}

function displayRecordName(record: SessionRecord): string {
  return record.sourceName ?? extractRecordName(record.label)
}

function previewableRecord(record: SessionRecord): boolean {
  return record.sourceKind === 'file' || record.sourceKind === 'skill'
}

function parseTodoOutput(output: string): TodoItem[] {
  const items: TodoItem[] = []
  for (const rawLine of output.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line === 'No todos.' || line.startsWith('(') || line.startsWith('###')) continue
    const match = line.match(/^\[( |>|x)\]\s*#([^:]+):\s*(.+)$/)
    if (!match) continue
    const statusMap: Record<string, TodoStatus> = {
      ' ': 'pending',
      '>': 'in_progress',
      x: 'completed',
    }
    items.push({
      id: match[2].trim(),
      text: match[3].trim(),
      status: statusMap[match[1]] ?? 'pending',
    })
  }
  return items
}

function MarkdownMessage({ content }: { content: string }) {
  return <MarkdownContent content={content} />
}

function formatRecordLabel(label: string): string {
  if (!label) return label
  const parenIdx = label.indexOf('(')
  if (parenIdx < 0) return `**${label}**`
  const toolName = label.slice(0, parenIdx)
  const argsStr = label.slice(parenIdx + 1, label.lastIndexOf(')')).trim()
  if (!argsStr) return `**${toolName}**()`
  try {
    const parsed = JSON.parse(argsStr)
    const pretty = JSON.stringify(parsed, null, 2)
    return `**${toolName}**\n\`\`\`json\n${pretty}\n\`\`\``
  } catch {
    return `**${toolName}**\n\`\`\`\n${argsStr}\n\`\`\``
  }
}

function extractRecordName(label: string): string {
  if (!label) return 'unknown'
  const parenIdx = label.indexOf('(')
  if (parenIdx <= 0) return label.trim()
  return label.slice(0, parenIdx).trim() || label.trim()
}

function formatAssistantMeta(message: SessionMessage, fallbackModel: string): string {
  const modelName = message.model ?? fallbackModel ?? 'unknown'
  if (message.roundSummary && message.roundSummary.modelCalls > 0) {
    return `${modelName} · ${message.roundSummary.totalTokens} tokens`
  }
  return ''
}

function TodoInProgressIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="7" pathLength="100" strokeDasharray="72 28" />
    </svg>
  )
}

function TodoPendingIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="7" />
    </svg>
  )
}

export function SessionView({
  token,
  currentSession,
  statusText,
  copiedText,
  onCopy,
  messages,
  sbcSelectionRequest,
  onSelectSBCEvent,
  records,
  artifacts,
  recordFilter,
  artifactFilter,
  onChangeRecordFilter,
  onChangeArtifactFilter,
  chatInput,
  onChatInputChange,
  isResponding,
  onSendOrStop,
  onArchiveSession,
  onDeleteSession,
  loading,
  error,
}: Props) {
  const visibleMessages = useMemo(
    () => messages.filter((item) => item.role === 'user' || item.role === 'assistant'),
    [messages],
  )
  const messagesRef = useRef<HTMLDivElement | null>(null)
  const [followLatest, setFollowLatest] = useState(true)
  const entries = useMemo<RenderEntry[]>(() => {
    const next: RenderEntry[] = []
    let currentGroup: CallGroup | null = null
    let pendingAssistantMessages: SessionMessage[] = []
    let recordCursor = 0
    let currentRound: number | null = null
    let awaitingResult = false

    const ensureGroup = (messageId: string) => {
      if (!currentGroup) {
        currentGroup = { id: messageId, calls: [] }
      }
    }

    const findRecord = (toolName: string): SessionRecord | null => {
      for (let index = recordCursor; index < records.length; index += 1) {
        if (extractRecordName(records[index].label) !== toolName) continue
        recordCursor = index + 1
        return records[index]
      }
      return null
    }

    const activeCall = (): ToolCallEntry | null => {
      if (!currentGroup || currentGroup.calls.length === 0) return null
      return currentGroup.calls[currentGroup.calls.length - 1]
    }

    const beginCall = (messageId: string, toolName: string) => {
      ensureGroup(messageId)
      currentGroup?.calls.push({
        id: messageId,
        name: toolName,
        round: currentRound,
        argumentsText: '',
        resultText: '',
        record: findRecord(toolName),
      })
      awaitingResult = false
    }

    const closeCurrent = () => {
      if (!currentGroup) return
      next.push({ type: 'callGroup', group: currentGroup })
      currentGroup = null
      const summarizedMessage = [...pendingAssistantMessages].reverse().find((message) => message.roundSummary)
      const finalMessage = summarizedMessage ?? (!isResponding ? pendingAssistantMessages[pendingAssistantMessages.length - 1] : undefined)
      if (finalMessage) {
        next.push({ type: 'message', message: finalMessage })
      }
      pendingAssistantMessages = []
      currentRound = null
      awaitingResult = false
    }

    for (const item of visibleMessages) {
      if (item.role === 'assistant' && item.kind === 'log') {
        const round = extractRound(item.content)
        const toolName = extractToolName(item.content)

        if (round !== null) {
          ensureGroup(item.id)
          currentRound = round
          awaitingResult = false
        }
        if (toolName) {
          beginCall(item.id, toolName)
          continue
        }
        const argumentsText = extractToolArguments(item.content)
        const call = activeCall()
        if (argumentsText !== null && call) {
          call.argumentsText = argumentsText
          continue
        }
        if (item.content.trim() === '### 本次工具调用的结果为：') {
          awaitingResult = true
          continue
        }
        if (awaitingResult && call) {
          call.resultText = item.content
          awaitingResult = false
        }
        continue
      }

      if (item.role === 'assistant' && currentGroup) {
        pendingAssistantMessages.push(item)
        continue
      }

      closeCurrent()
      next.push({ type: 'message', message: item })
    }

    closeCurrent()
    return next
  }, [visibleMessages, records, isResponding])
  const todoBoard = useMemo<TodoBoard | null>(() => {
    let currentTool: string | null = null
    let awaitingOutput = false
    let latestOutput = ''

    for (const item of visibleMessages) {
      if (item.role !== 'assistant' || item.kind !== 'log') continue
      const line = item.content.trim()
      const toolName = extractTodoToolName(line)
      if (toolName) {
        currentTool = toolName
        awaitingOutput = false
        continue
      }
      if (line.includes('本次工具调用的结果为：')) {
        awaitingOutput = currentTool === 'todo'
        continue
      }
      if (awaitingOutput && currentTool === 'todo') {
        latestOutput = item.content
        awaitingOutput = false
        currentTool = null
      }
    }

    if (!latestOutput) return null
    const items = parseTodoOutput(latestOutput)
    return items.length ? { items } : null
  }, [visibleMessages])
  const todoSignature = useMemo(() => {
    if (!todoBoard) return ''
    return todoBoard.items.map((item) => `${item.id}:${item.status}:${item.text}`).join('|')
  }, [todoBoard])
  const todoAllCompleted = !!todoBoard && todoBoard.items.length > 0 && todoBoard.items.every((item) => item.status === 'completed')
  const [todoExpanded, setTodoExpanded] = useState(false)
  const todoSignatureRef = useRef('')
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
  const [expandedCalls, setExpandedCalls] = useState<Record<string, boolean>>({})
  const [expandedRecords, setExpandedRecords] = useState<Record<string, boolean>>({})
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [sidePaneOpen, setSidePaneOpen] = useState(true)
  const [sidePaneWidth, setSidePaneWidth] = useState(() => {
    if (typeof window === 'undefined') return 360
    const raw = window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY)
    const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN
    return Number.isFinite(parsed) ? parsed : 360
  })
  const [resizingSidebar, setResizingSidebar] = useState(false)
  const [sidePaneTab, setSidePaneTab] = useState<'preview' | 'records' | 'artifacts'>('records')
  const [previewRecordId, setPreviewRecordId] = useState('')
  const [previewData, setPreviewData] = useState<PreviewData | null>(null)
  const [previewMarkdownMode, setPreviewMarkdownMode] = useState<'rendered' | 'source'>('rendered')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const resizeOriginRef = useRef<{ startX: number; startWidth: number } | null>(null)

  const clampSidePaneWidth = (value: number): number => {
    if (typeof window === 'undefined') return Math.min(Math.max(value, SIDEBAR_MIN_WIDTH), SIDEBAR_MAX_WIDTH)
    const viewportMax = window.innerWidth - CHAT_MIN_WIDTH
    const maxAllowed = Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, viewportMax))
    return Math.min(Math.max(value, SIDEBAR_MIN_WIDTH), maxAllowed)
  }

  useEffect(() => {
    setExpandedGroups((prev) => {
      const next: Record<string, boolean> = {}
      for (const entry of entries) {
        if (entry.type !== 'callGroup') continue
        next[entry.group.id] = prev[entry.group.id] ?? false
      }
      const prevKeys = Object.keys(prev)
      const nextKeys = Object.keys(next)
      if (prevKeys.length === nextKeys.length && prevKeys.every((key) => prev[key] === next[key])) {
        return prev
      }
      return next
    })
  }, [entries])

  useEffect(() => {
    setExpandedCalls((prev) => {
      const next: Record<string, boolean> = {}
      for (const entry of entries) {
        if (entry.type !== 'callGroup') continue
        for (const call of entry.group.calls) {
          next[call.id] = prev[call.id] ?? false
        }
      }
      return next
    })
  }, [entries])

  useEffect(() => {
    setExpandedRecords((prev) => {
      const next: Record<string, boolean> = {}
      for (const item of records) {
        next[item.id] = prev[item.id] ?? false
      }
      const prevKeys = Object.keys(prev)
      const nextKeys = Object.keys(next)
      if (prevKeys.length === nextKeys.length && prevKeys.every((key) => prev[key] === next[key])) {
        return prev
      }
      return next
    })
  }, [records])

  useEffect(() => {
    setPreviewRecordId('')
    setPreviewData(null)
    setPreviewMarkdownMode('rendered')
    setPreviewError('')
    setPreviewLoading(false)
    setSidePaneTab('records')
    setSidePaneOpen(true)
  }, [currentSession.id])

  const previewRecord = useMemo(() => {
    if (!previewRecordId) return null
    return records.find((item) => item.id === previewRecordId) ?? null
  }, [previewRecordId, records])

  useEffect(() => {
    if (!previewRecordId) return
    if (!previewRecord || !previewableRecord(previewRecord)) {
      setPreviewData(null)
      setPreviewError('')
      setPreviewLoading(false)
      return
    }
    let cancelled = false
    setPreviewLoading(true)
    setPreviewError('')
    void (async () => {
      try {
        const preview = await fetchSessionPreview(token, currentSession.id, previewRecord.id)
        if (cancelled) return
        setPreviewData(preview)
        setPreviewMarkdownMode(preview.contentKind === 'markdown' ? 'rendered' : 'source')
      } catch (error) {
        if (cancelled) return
        setPreviewError(error instanceof Error ? error.message : '预览加载失败')
        setPreviewData(null)
      } finally {
        if (!cancelled) setPreviewLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, currentSession.id, previewRecordId, previewRecord?.id, previewRecord?.sourceKind, previewRecord?.sourcePath, previewRecord?.sourceName, previewRecord?.label])

  useEffect(() => {
    if (!todoBoard) {
      todoSignatureRef.current = ''
      setTodoExpanded(false)
      return
    }
    if (todoSignatureRef.current === todoSignature) return
    todoSignatureRef.current = todoSignature
    setTodoExpanded(!todoAllCompleted)
  }, [todoBoard, todoSignature, todoAllCompleted])

  useEffect(() => {
    setFollowLatest(true)
  }, [currentSession.id])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const normalized = clampSidePaneWidth(sidePaneWidth)
    if (normalized !== sidePaneWidth) {
      setSidePaneWidth(normalized)
      return
    }
    window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(normalized))
  }, [sidePaneWidth])

  useEffect(() => {
    const handleResize = () => setSidePaneWidth((prev) => clampSidePaneWidth(prev))
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    if (!resizingSidebar) return

    const onMouseMove = (event: MouseEvent) => {
      const origin = resizeOriginRef.current
      if (!origin) return
      const delta = event.clientX - origin.startX
      setSidePaneWidth(clampSidePaneWidth(origin.startWidth - delta))
    }

    const onMouseUp = () => {
      resizeOriginRef.current = null
      setResizingSidebar(false)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [resizingSidebar])

  useLayoutEffect(() => {
    const node = messagesRef.current
    if (!node || !followLatest) return
    node.scrollTop = node.scrollHeight
  }, [entries, loading, error, isResponding, followLatest])

  const handleMessagesScroll = () => {
    const node = messagesRef.current
    if (!node) return
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight
    setFollowLatest(distanceToBottom <= 24)
  }

  const openPreviewForRecord = (record: SessionRecord) => {
    if (!previewableRecord(record)) return
    setPreviewRecordId(record.id)
    setSidePaneTab('preview')
    setSidePaneOpen(true)
  }

  const onSidebarResizeHandleMouseDown = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    resizeOriginRef.current = { startX: event.clientX, startWidth: sidePaneWidth }
    setResizingSidebar(true)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }

  const sessionLayoutStyle = sidePaneOpen
    ? ({ '--side-pane-width': `${sidePaneWidth}px` } as React.CSSProperties)
    : undefined

  return (
    <div className="sessionView">
      {showDeleteConfirm && (
        <div className="modalMask" onClick={() => setShowDeleteConfirm(false)}>
          <div className="modalCard" style={{ width: 'min(420px, 95vw)' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 12 }}>确认删除会话</div>
            <p style={{ color: '#cbd5e1', marginBottom: 16 }}>
              确定要删除会话「<strong>{currentSession.name}</strong>」吗？此操作不可撤销。
            </p>
            <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" onClick={() => setShowDeleteConfirm(false)}>
                取消
              </button>
              <button
                type="button"
                className="dangerBtn"
                onClick={() => {
                  setShowDeleteConfirm(false)
                  onDeleteSession()
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="panel">
        <div className="row between">
          <div>
            <strong>{currentSession.name}</strong>
            <div className="muted">
              状态：{statusText[currentSession.status]} · 模型：{currentSession.model ?? 'gemini-1.5-flash'}
            </div>
          </div>
          <div className="row">
            {currentSession.status === 'active' && (
              <button type="button" onClick={onArchiveSession}>
                归档
              </button>
            )}
            <button type="button" className="dangerBtn" onClick={() => setShowDeleteConfirm(true)}>
              删除
            </button>
          </div>
        </div>
      </div>
      <div className={`sessionLayout ${sidePaneOpen ? '' : 'sessionLayoutCollapsed'} ${resizingSidebar ? 'sessionLayoutResizing' : ''}`} style={sessionLayoutStyle}>
        <div className="panel chatShell">
          <div className="messages" ref={messagesRef} onScroll={handleMessagesScroll}>
            {loading && <div className="muted">加载中...</div>}
            {!loading && error && <div className="runErrorBanner">{error}</div>}
            {!loading && entries.length === 0 && <div className="muted">暂无会话消息</div>}
            {!loading &&
              entries.map((entry) => {
                if (entry.type === 'callGroup') {
                  const group = entry.group
                  const expanded = expandedGroups[group.id] ?? false
                  return (
                    <div key={group.id} className="chatRow assistant">
                      <div className="assistantBlock callGroupCard">
                        <button
                          type="button"
                          className="callGroupSummary"
                          onClick={() => setExpandedGroups((prev) => ({ ...prev, [group.id]: !expanded }))}
                          aria-expanded={expanded}
                        >
                          <span>{expanded ? '▾' : '▸'} {summarizeCallGroup(group)}</span>
                        </button>
                        {expanded && (
                          <div className="callGroupDetails">
                            {group.calls.length ? (
                              group.calls.map((call, callIdx) => {
                                const canPreview = !!call.record && previewableRecord(call.record)
                                const callExpanded = expandedCalls[call.id] ?? false
                                return (
                                  <div key={`${group.id}_${call.id}_${callIdx}`} className="callTimelineItem">
                                    <div className="callTimelineRail" aria-hidden="true">
                                      <span className="callTimelineDot" />
                                      {callIdx < group.calls.length - 1 ? <span className="callTimelineTail" /> : null}
                                    </div>
                                    <div className="callTimelineCard">
                                      <button
                                        type="button"
                                        className="callBrief"
                                        onClick={() => {
                                          if (canPreview && call.record) {
                                            openPreviewForRecord(call.record)
                                            return
                                          }
                                          setExpandedCalls((prev) => ({ ...prev, [call.id]: !callExpanded }))
                                        }}
                                        aria-expanded={canPreview ? undefined : callExpanded}
                                      >
                                        <span className="recordTypeTag">{call.record?.type ?? 'tool'}</span>
                                        <span className="callBriefText">{toolActionLabel(call)}</span>
                                        <span className="callRecordIndex">{canPreview ? '在右侧查看' : callExpanded ? '▾' : '▸'}</span>
                                      </button>
                                      {callExpanded && !canPreview && (
                                        <div className="callDetail">
                                          {call.argumentsText && (
                                            <div>
                                              <div className="callDetailLabel">参数</div>
                                              <pre>{call.argumentsText}</pre>
                                            </div>
                                          )}
                                          {call.resultText && (
                                            <div>
                                              <div className="callDetailLabel">结果</div>
                                              <pre>{call.resultText}</pre>
                                            </div>
                                          )}
                                          {!call.argumentsText && !call.resultText && <div className="muted">暂无可展示的调用详情</div>}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                )
                              })
                            ) : (
                              <div className="muted">暂无可展示的调用明细</div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                }

                const item = entry.message
                const assistantMetaText = item.role === 'assistant' ? formatAssistantMeta(item, currentSession.model ?? 'unknown') : ''
                return (
                  <div key={item.id} className={`chatRow ${item.role === 'user' ? 'user' : 'assistant'}`}>
                    {item.role === 'user' ? (
                      <div className="msg user">
                        <MarkdownMessage content={item.content} />
                      </div>
                    ) : (
                      <div className={`assistantBlock ${item.kind === 'error' ? 'modelErrorBlock' : ''}`}>
                        {item.kind === 'error' && <div className="modelErrorTitle">基座模型调用异常</div>}
                        <MarkdownMessage content={item.content} />
                        <div className="assistantMeta">
                          <button
                            type="button"
                            className="copyBtn"
                            onClick={() => onCopy(item.content)}
                            aria-label="复制回复"
                            title={copiedText === item.content ? '已复制' : '复制'}
                          >
                            {copiedText === item.content ? '✓' : <CopyIcon />}
                          </button>
                          {assistantMetaText ? <span className="assistantMetaRight">{assistantMetaText}</span> : <span />}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            {!loading && sbcSelectionRequest && (
              <div className="chatRow assistant">
                <section className="sbcSelectionPanel" aria-label="无连接中断事件选择">
                  <div className="sbcSelectionTitle">{sbcSelectionRequest.prompt}</div>
                  <div className="sbcSelectionGrid">
                    {sbcSelectionRequest.candidates.map((event, index) => (
                      <article className="sbcEventCard" key={event.event_id}>
                        <div className="sbcEventHead">
                          <strong>事件 {index + 1}</strong>
                          <span>{SBC_PATTERN_LABELS[event.pattern] ?? event.pattern}</span>
                        </div>
                        <div className="sbcEventTime">
                          {event.interruption_start_bdt} — {event.interruption_end_bdt}
                        </div>
                        <div className="sbcEventMeta">
                          <span>持续 {formatDuration(event.duration_seconds)}</span>
                          <span>{event.satellite_count}颗卫星</span>
                          <span>
                            落地星：
                            {event.landing_satellites.length
                              ? event.landing_satellites.join('、')
                              : '未获取'}
                          </span>
                        </div>
                        <details>
                          <summary>查看卫星和事件ID</summary>
                          <div>{event.satellites.join('、')}</div>
                          <code>{event.event_id}</code>
                        </details>
                        <button
                          type="button"
                          className="primary sbcEventSelectButton"
                          disabled={isResponding}
                          onClick={() => onSelectSBCEvent(event.event_id)}
                        >
                          排查此事件
                        </button>
                      </article>
                    ))}
                  </div>
                </section>
              </div>
            )}
            {!loading && isResponding && (
              <div className="chatRow assistant">
                <div className="assistantBlock runningBlock">
                  <RunningGridIcon />
                  <div className="assistantPlain">正在运行，请稍候…</div>
                </div>
              </div>
            )}
          </div>

          <div className="chatComposer">
            {todoBoard && (
              <div className="todoPanel">
                <button type="button" className="todoPanelHead todoPanelToggle" onClick={() => setTodoExpanded((v) => !v)}>
                  <strong>待办事项</strong>
                  <div className="todoCount">
                    {todoBoard.items.filter((item) => item.status === 'completed').length}/{todoBoard.items.length}
                    <span className="todoChevron">{todoExpanded ? '▾' : '▸'}</span>
                  </div>
                </button>
                {todoExpanded && (
                  <ul className="todoList">
                    {todoBoard.items.map((item) => (
                      <li key={item.id} className={`todoItem todoItem_${item.status}`}>
                        <span className={`todoStatus todoStatus_${item.status}`} title={item.status}>
                          {item.status === 'in_progress' ? (
                            <TodoInProgressIcon />
                          ) : item.status === 'pending' ? (
                            <TodoPendingIcon />
                          ) : (
                            <span className="todoStatusGlyph">✓</span>
                          )}
                        </span>
                        <span className="todoText">{item.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <textarea
              rows={2}
              value={chatInput}
              onChange={(e) => onChatInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
                e.preventDefault()
                if (!isResponding && chatInput.trim()) onSendOrStop()
              }}
              placeholder="输入你的问题，Enter 发送，Shift+Enter 换行"
            />
            <div className="row composerActions">
              <button type="button">上传文件</button>
              <button
                className="primary iconActionBtn"
                type="button"
                onClick={onSendOrStop}
                disabled={!isResponding && !chatInput.trim()}
                title={isResponding ? '停止本次生成' : '发送'}
                aria-label={isResponding ? '停止本次生成' : '发送消息'}
              >
                {isResponding ? <StopIcon /> : <SendIcon />}
              </button>
            </div>
          </div>
        </div>

        <div className={`sidebar ${sidePaneOpen ? '' : 'sidebarCollapsed'}`}>
          {sidePaneOpen ? (
            <div className="panel sidePane sidePaneShell">
              <button
                type="button"
                className="sidePaneResizeHandle"
                onMouseDown={onSidebarResizeHandleMouseDown}
                aria-label="拖动调整右侧栏宽度"
                title="拖动调整宽度"
              />
              <div className="paneHead sidePaneHead">
                <div className="sidePaneTabs">
                  <button
                    type="button"
                    className={sidePaneTab === 'preview' ? 'activeView' : ''}
                    onClick={() => setSidePaneTab('preview')}
                  >
                    预览
                  </button>
                  <button
                    type="button"
                    className={sidePaneTab === 'records' ? 'activeView' : ''}
                    onClick={() => setSidePaneTab('records')}
                  >
                    调用记录
                  </button>
                  <button
                    type="button"
                    className={sidePaneTab === 'artifacts' ? 'activeView' : ''}
                    onClick={() => setSidePaneTab('artifacts')}
                  >
                    输出结果
                  </button>
                </div>
                <button type="button" className="iconTinyBtn sidebarToggleBtn" onClick={() => setSidePaneOpen(false)} aria-label="收起右侧栏">
                  ▸
                </button>
              </div>
              <div className="paneBody sidePaneBody">
                {sidePaneTab === 'preview' && (
                  <div className="previewPane">
                    {previewLoading && <div className="muted">正在加载预览...</div>}
                    {!previewLoading && previewError && <div className="errorText">{previewError}</div>}
                    {!previewLoading && !previewError && !previewData && (
                      <div className="muted">点击调用块里的文件名或 Skill 名查看内容</div>
                    )}
                    {!previewLoading && !previewError && previewData && (
                      <>
                        <div className="previewHead previewStickyHead">
                          <div className="previewMeta">
                            <strong>{previewData.title}</strong>
                            <div className="muted previewSourcePath">
                              {previewData.sourceKind === 'skill' ? 'Skill' : '文件'} · {previewData.sourcePath}
                            </div>
                          </div>
                          {previewData.contentKind === 'markdown' && (
                            <div className="previewModeTabs" role="tablist" aria-label="Markdown 预览模式">
                              <button
                                type="button"
                                className={previewMarkdownMode === 'rendered' ? 'active' : ''}
                                onClick={() => setPreviewMarkdownMode('rendered')}
                                role="tab"
                                aria-selected={previewMarkdownMode === 'rendered'}
                                aria-label="查看渲染结果"
                                title="渲染结果"
                              >
                                <PreviewRenderedIcon />
                              </button>
                              <button
                                type="button"
                                className={previewMarkdownMode === 'source' ? 'active' : ''}
                                onClick={() => setPreviewMarkdownMode('source')}
                                role="tab"
                                aria-selected={previewMarkdownMode === 'source'}
                                aria-label="查看源代码"
                                title="源代码"
                              >
                                <PreviewSourceIcon />
                              </button>
                            </div>
                          )}
                        </div>
                        {previewData.contentKind === 'markdown' ? (
                          previewMarkdownMode === 'rendered' ? (
                            <div className="previewMarkdown">
                              <MarkdownMessage content={previewData.content} />
                            </div>
                          ) : (
                            <pre className="previewCode">{previewData.content}</pre>
                          )
                        ) : (
                          <pre className="previewCode">{previewData.content}</pre>
                        )}
                      </>
                    )}
                  </div>
                )}
                {sidePaneTab === 'records' && (
                  <div className="recordsPane">
                    <div className="paneToolbar">
                      <select value={recordFilter} onChange={(e) => onChangeRecordFilter(e.target.value as 'all' | 'skills' | 'tools')}>
                        <option value="all">全部</option>
                        <option value="skills">技能（Skills）</option>
                        <option value="tools">工具（Tools）</option>
                      </select>
                    </div>
                    <ul className="recordList">
                      {records.length === 0 && <li className="muted">暂无调用记录</li>}
                      {records.map((item) => {
                        const canPreview = previewableRecord(item)
                        return (
                          <li key={item.id} className="recordItem">
                            <button
                              type="button"
                              className="recordSummaryBtn"
                              onClick={() => {
                                setExpandedRecords((prev) => ({ ...prev, [item.id]: !prev[item.id] }))
                                if (canPreview) openPreviewForRecord(item)
                              }}
                              aria-expanded={expandedRecords[item.id] ?? false}
                            >
                              <span className="recordTypeTag">{item.type}</span>
                              {canPreview ? (
                                <span className="recordName recordNameLink">{displayRecordName(item)}</span>
                              ) : (
                                <span className="recordName">{displayRecordName(item)}</span>
                              )}
                              <span className="recordExpandIcon">{expandedRecords[item.id] ? '▾' : '▸'}</span>
                            </button>
                            {(expandedRecords[item.id] ?? false) && canPreview && (
                              <div className="recordLabel">已在右侧预览栏中打开。</div>
                            )}
                            {(expandedRecords[item.id] ?? false) && !canPreview && (
                              <div className="recordLabel">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatRecordLabel(item.label)}</ReactMarkdown>
                              </div>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  </div>
                )}
                {sidePaneTab === 'artifacts' && (
                  <div className="artifactsPane">
                    <div className="paneToolbar">
                      <select value={artifactFilter} onChange={(e) => onChangeArtifactFilter(e.target.value as 'all' | 'doc' | 'image' | 'data')}>
                        <option value="all">全部</option>
                        <option value="doc">文档</option>
                        <option value="image">图片</option>
                        <option value="data">数据</option>
                      </select>
                    </div>
                    <div className="artifactList">
                      {artifacts.length === 0 && <div className="muted">暂无输出结果</div>}
                      {artifacts.map((item) => (
                        <div key={item.id} className="artifactRow">
                          <ArtifactLink token={token} artifact={item} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <button type="button" className="sidebarRail" onClick={() => setSidePaneOpen(true)} aria-label="展开右侧栏">
              ◂
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
