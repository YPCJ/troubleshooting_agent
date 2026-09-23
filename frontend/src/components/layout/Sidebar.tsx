import { SessionGroup } from './SessionGroup'
import type { Role, SessionGroups, SessionItem, ViewKey } from '../../types/app'

export function Sidebar({
  sessions,
  currentSession,
  currentView,
  onSelectSession,
  onArchiveSession,
  onActivateSession,
  onDeleteSession,
  onSwitchView,
  role,
}: {
  sessions: SessionGroups
  currentSession: SessionItem
  currentView: ViewKey
  onSelectSession: (session: SessionItem) => void
  onArchiveSession: (session: SessionItem) => void
  onActivateSession: (session: SessionItem) => void
  onDeleteSession: (session: SessionItem) => void
  onSwitchView: (view: ViewKey) => void
  role: Role
}) {
  const canManageUsers = role === 'admin' || role === 'super_admin'

  return (
    <aside className="left">
      <div className="section head">
        <div className="sessionTitleRow">
          <strong>会话</strong>
          <span className="infoHint" aria-label="会话分组说明">
            i
            <span className="tooltip">活跃 = 运行中；归档 = 已归档历史会话</span>
          </span>
        </div>
        <button type="button" onClick={() => onSwitchView('newSession')}>
          + New
        </button>
      </div>
      <div className="section sessionsPane">
        <SessionGroup
          title="活跃"
          items={sessions.active}
          currentSessionId={currentSession.id}
          onSelect={onSelectSession}
          onArchive={onArchiveSession}
          onActivate={onActivateSession}
          onDelete={onDeleteSession}
        />
      </div>
      <div className="nav">
        <button type="button" className={currentView === 'session' ? 'activeView' : ''} onClick={() => onSwitchView('session')}>
          当前 Session
        </button>
        <button type="button" className={currentView === 'apps' ? 'activeView' : ''} onClick={() => onSwitchView('apps')}>
          智能体 / 应用
        </button>
        <button
          type="button"
          className={currentView === 'archivedSessions' ? 'activeView' : ''}
          onClick={() => onSwitchView('archivedSessions')}
        >
          已归档 Session
        </button>
        <button type="button" className={currentView === 'skills' ? 'activeView' : ''} onClick={() => onSwitchView('skills')}>
          Skills 管理
        </button>
        <button type="button" className={currentView === 'tools' ? 'activeView' : ''} onClick={() => onSwitchView('tools')}>
          Tools 管理
        </button>
        <button type="button" className={currentView === 'results' ? 'activeView' : ''} onClick={() => onSwitchView('results')}>
          结果中心
        </button>
        {canManageUsers && (
          <button type="button" className={currentView === 'models' ? 'activeView' : ''} onClick={() => onSwitchView('models')}>
            模型管理
          </button>
        )}
        {canManageUsers && (
          <button type="button" className={currentView === 'users' ? 'activeView' : ''} onClick={() => onSwitchView('users')}>
            用户管理
          </button>
        )}
      </div>
    </aside>
  )
}
