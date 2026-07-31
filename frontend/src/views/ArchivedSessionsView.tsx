import type { SessionItem } from '../types/app'

export function ArchivedSessionsView({
  items,
  onActivate,
  onDelete,
}: {
  items: SessionItem[]
  onActivate: (session: SessionItem) => void
  onDelete: (session: SessionItem) => void
}) {
  return (
    <div className="panel">
      <strong>已归档 Session</strong>
      <div className="archivedList">
        {items.length === 0 && <div className="muted">暂无已归档会话</div>}
        {items.map((item) => (
          <div key={item.id} className="archivedRow">
            <div className="archivedInfo">
              <div>{item.name}</div>
              <div className="muted">{item.id} · {item.updated}</div>
            </div>
            <div className="row">
              <button type="button" onClick={() => onActivate(item)}>转为活跃</button>
              <button type="button" className="dangerBtn" onClick={() => onDelete(item)}>删除</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
