import { useEffect, useRef, useState } from 'react'
import type { SessionItem } from '../../types/app'

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
  const [menuTarget, setMenuTarget] = useState<SessionItem | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current) return
      if (!menuRef.current.contains(event.target as Node)) {
        setMenuTarget(null)
      }
    }

    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [])

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
          <div
            className="sessionItemActions"
            ref={(el) => {
              if (menuTarget?.id === s.id) {
                menuRef.current = el
              }
            }}
          >
            <button
              type="button"
              className="iconTinyBtn sessionMenuBtn"
              title="更多操作"
              aria-label="更多操作"
              aria-expanded={menuTarget?.id === s.id}
              onClick={() => setMenuTarget((current) => (current?.id === s.id ? null : s))}
            >
              ⋮
            </button>
            {menuTarget?.id === s.id && (
              <div className="sessionMenu">
                {s.status === 'active' ? (
                  <button
                    type="button"
                    className="sessionMenuItem"
                    onClick={() => {
                      setMenuTarget(null)
                      onArchive(s)
                    }}
                  >
                    归档
                  </button>
                ) : (
                  <button
                    type="button"
                    className="sessionMenuItem"
                    onClick={() => {
                      setMenuTarget(null)
                      onActivate(s)
                    }}
                  >
                    转为活跃
                  </button>
                )}
                <button
                  type="button"
                  className="sessionMenuItem dangerBtn"
                  onClick={() => {
                    setMenuTarget(null)
                    setDeleteTarget(s)
                  }}
                >
                  删除
                </button>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
