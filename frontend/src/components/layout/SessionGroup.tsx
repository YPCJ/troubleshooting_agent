import { useState } from 'react'
import type { SessionItem } from '../../types/app'

function ArchiveIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="3" y="4" width="14" height="4" rx="1.2" />
      <rect x="4" y="8" width="12" height="8" rx="1.2" />
      <path d="M8 11h4" />
    </svg>
  )
}

function ActivateIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3v8" />
      <path d="M7 6l3-3l3 3" />
      <rect x="4" y="12" width="12" height="4" rx="1.2" />
    </svg>
  )
}

function DeleteIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 6h12" />
      <path d="M7 6V4h6v2" />
      <rect x="6" y="6" width="8" height="10" rx="1.2" />
    </svg>
  )
}

export function SessionGroup({
  title,
  items,
  currentSessionId,
  onSelect,
  onArchive,
  onActivate,
  onDelete,
}: {
  title: string
  items: SessionItem[]
  currentSessionId: string
  onSelect: (item: SessionItem) => void
  onArchive: (item: SessionItem) => void
  onActivate: (item: SessionItem) => void
  onDelete: (item: SessionItem) => void
}) {
  const [deleteTarget, setDeleteTarget] = useState<SessionItem | null>(null)

  return (
    <div className="group">
      {deleteTarget && (
        <div className="modalMask" onClick={() => setDeleteTarget(null)}>
          <div className="modalCard" style={{ width: 'min(420px, 95vw)' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 12 }}>确认删除会话</div>
            <p style={{ color: '#cbd5e1', marginBottom: 16 }}>
              确定要删除会话「<strong>{deleteTarget.name}</strong>」吗？此操作不可撤销。
            </p>
            <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" onClick={() => setDeleteTarget(null)}>
                取消
              </button>
              <button
                type="button"
                className="dangerBtn"
                onClick={() => {
                  const target = deleteTarget
                  setDeleteTarget(null)
                  onDelete(target)
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="groupTitle">{title}</div>
      {items.map((s) => (
        <div key={s.id} className={`sessionItem ${s.id === currentSessionId ? 'active' : ''}`}>
          <button type="button" className="sessionMainBtn" onClick={() => onSelect(s)}>
            <div>{s.name}</div>
            <div className="muted">
              {s.id} · {s.status} · {s.updated}
            </div>
          </button>
          <div className="sessionItemActions">
            {s.status === 'active' && (
              <button
                type="button"
                className="iconTinyBtn"
                title="归档"
                aria-label="归档"
                onClick={() => onArchive(s)}
              >
                <ArchiveIcon />
              </button>
            )}
            {s.status === 'archived' && (
              <button
                type="button"
                className="iconTinyBtn"
                title="转为活跃"
                aria-label="转为活跃"
                onClick={() => onActivate(s)}
              >
                <ActivateIcon />
              </button>
            )}
            <button
              type="button"
              className="iconTinyBtn dangerBtn"
              title="删除"
              aria-label="删除"
              onClick={() => setDeleteTarget(s)}
            >
              <DeleteIcon />
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
