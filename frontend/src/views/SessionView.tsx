import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ArtifactItem, SessionItem, SessionMessage, SessionRecord, SessionStatus } from '../types/app'

type Props = {
  currentSession: SessionItem
  statusText: Record<SessionStatus, string>
  copiedText: string
  onCopy: (text: string) => void
  messages: SessionMessage[]
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

function RunningGridIcon() {
  return (
    <span className="runningGrid" aria-hidden="true">
      {Array.from({ length: 9 }).map((_, idx) => (
        <span key={idx} />
      ))}
    </span>
  )
}

type CallGroup = {
  id: string
  round: number | null
  lines: string[]
  tools: string[]
}

type RenderEntry =
  | { type: 'message'; message: SessionMessage }
  | { type: 'callGroup'; group: CallGroup }

function extractRound(line: string): number | null {
  const match = line.match(/第(\d+)次调用/)
  return match ? Number(match[1]) : null
}

function extractToolName(line: string): string | null {
  const match = line.match(/\[tool call\]\s*([a-zA-Z0-9_-]+)\(\)\s*requested/)
  return match ? match[1] : null
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="mdContent">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  )
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

export function SessionView({
  currentSession,
  statusText,
  copiedText,
  onCopy,
  messages,
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
  const visibleMessages = messages.filter((item) => item.role === 'user' || item.role === 'assistant')
  const entries = useMemo<RenderEntry[]>(() => {
    const next: RenderEntry[] = []
    let currentGroup: CallGroup | null = null

    const closeCurrent = () => {
      if (!currentGroup) return
      currentGroup.tools = Array.from(new Set(currentGroup.tools))
      next.push({ type: 'callGroup', group: currentGroup })
      currentGroup = null
    }

    for (const item of visibleMessages) {
      if (item.role === 'assistant' && item.kind === 'log') {
        const round = extractRound(item.content)
        const toolName = extractToolName(item.content)

        if (round !== null) {
          closeCurrent()
          currentGroup = { id: item.id, round, lines: [item.content], tools: toolName ? [toolName] : [] }
          continue
        }

        if (!currentGroup) {
          currentGroup = { id: item.id, round: null, lines: [item.content], tools: toolName ? [toolName] : [] }
        } else {
          currentGroup.lines.push(item.content)
          if (toolName) currentGroup.tools.push(toolName)
        }
        continue
      }

      closeCurrent()
      next.push({ type: 'message', message: item })
    }

    closeCurrent()
    return next
  }, [visibleMessages])
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
  const [expandedRecords, setExpandedRecords] = useState<Record<string, boolean>>({})
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  useEffect(() => {
    setExpandedGroups((prev) => {
      const next: Record<string, boolean> = {}
      for (const entry of entries) {
        if (entry.type !== 'callGroup') continue
        next[entry.group.id] = prev[entry.group.id] ?? false
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
      return next
    })
  }, [records])

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
      <div className="sessionLayout">
        <div className="panel chatShell">
          <div className="messages">
            {loading && <div className="muted">加载中...</div>}
            {!loading && error && <div className="errorText">{error}</div>}
            {!loading && !error && entries.length === 0 && <div className="muted">暂无会话消息</div>}
            {!loading &&
              !error &&
              entries.map((entry) => {
                if (entry.type === 'callGroup') {
                  const group = entry.group
                  const expanded = expandedGroups[group.id] ?? false
                  const roundLabel = group.round ? `第${group.round}次调用` : '模型调用'
                  const toolsLabel = group.tools.length ? group.tools.join('、') : '无'
                  return (
                    <div key={group.id} className="chatRow assistant">
                      <div className="assistantBlock callGroupCard">
                        <button
                          type="button"
                          className="callGroupSummary"
                          onClick={() => setExpandedGroups((prev) => ({ ...prev, [group.id]: !expanded }))}
                          aria-expanded={expanded}
                        >
                          <span>{expanded ? '▾' : '▸'} {roundLabel}</span>
                          <span className="callGroupTools">调用工具：{toolsLabel}</span>
                        </button>
                        {expanded && (
                          <div className="assistantLog">
                            {group.lines.map((line, idx) => (
                              <MarkdownMessage key={`${group.id}_${idx}`} content={line} />
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                }

                const item = entry.message
                return (
                  <div key={item.id} className={`chatRow ${item.role === 'user' ? 'user' : 'assistant'}`}>
                    {item.role === 'user' ? (
                      <div className="msg user">
                        <MarkdownMessage content={item.content} />
                      </div>
                    ) : (
                      <div className="assistantBlock">
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
                          <span className="assistantMetaRight">
                            {item.model ?? currentSession.model ?? 'unknown'} · {item.tokens ?? 0} tokens
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            {!loading && !error && isResponding && (
              <div className="chatRow assistant">
                <div className="assistantBlock runningBlock">
                  <RunningGridIcon />
                  <div className="assistantPlain">正在运行，请稍候…</div>
                </div>
              </div>
            )}
          </div>

          <div className="chatComposer">
            <textarea rows={2} value={chatInput} onChange={(e) => onChatInputChange(e.target.value)} placeholder="输入你的问题，回车发送（Mock）" />
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

        <div className="sidebar">
          <div className="panel sidePane">
            <div className="paneHead">
              <strong>调用记录</strong>
              <select value={recordFilter} onChange={(e) => onChangeRecordFilter(e.target.value as 'all' | 'skills' | 'tools')}>
                <option value="all">全部</option>
                <option value="skills">技能（Skills）</option>
                <option value="tools">工具（Tools）</option>
              </select>
            </div>
            <div className="paneBody">
              <ul className="recordList">
                {records.map((item) => (
                  <li key={item.id} className="recordItem">
                    <button
                      type="button"
                      className="recordSummaryBtn"
                      onClick={() => setExpandedRecords((prev) => ({ ...prev, [item.id]: !prev[item.id] }))}
                      aria-expanded={expandedRecords[item.id] ?? false}
                    >
                      <span className="recordTypeTag">{item.type}</span>
                      <span className="recordName">{extractRecordName(item.label)}</span>
                      <span className="recordExpandIcon">{expandedRecords[item.id] ? '▾' : '▸'}</span>
                    </button>
                    {(expandedRecords[item.id] ?? false) && (
                      <div className="recordLabel">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatRecordLabel(item.label)}</ReactMarkdown>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="panel sidePane">
            <div className="paneHead">
              <strong>输出结果</strong>
              <select value={artifactFilter} onChange={(e) => onChangeArtifactFilter(e.target.value as 'all' | 'doc' | 'image' | 'data')}>
                <option value="all">全部</option>
                <option value="doc">文档</option>
                <option value="image">图片</option>
                <option value="data">数据</option>
              </select>
            </div>
            <div className="paneBody">
              {artifacts.map((item) => (
                <div key={item.id} className="artifactRow">
                  <div className="artifactName">{item.name}</div>
                  <div className="artifactPath">{item.path}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
