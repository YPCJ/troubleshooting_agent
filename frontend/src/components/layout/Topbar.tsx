import type { Role, ViewKey } from '../../types/app'

export function Topbar({
  currentView,
  currentSessionName,
  role,
  username,
  userMenuOpen,
  onToggleUserMenu,
  onOpenUserSettings,
  onLogout,
  onBackSession,
}: {
  currentView: ViewKey
  currentSessionName: string
  role: Role
  username: string
  userMenuOpen: boolean
  onToggleUserMenu: () => void
  onOpenUserSettings: () => void
  onLogout: () => void
  onBackSession: () => void
}) {
  const roleText = role === 'super_admin' ? '超级管理员' : role === 'admin' ? '管理员' : '普通用户'
  const displayName = username || roleText

  return (
    <div className="topbar">
      <div>
        <strong>{currentView === 'session' ? '当前 Session' : '管理视图'}</strong>
        <span className="muted"> · {currentSessionName}</span>
      </div>
      <div className="row">
        {currentView !== 'session' && (
          <button type="button" className="ghost" onClick={onBackSession}>
            返回当前 Session
          </button>
        )}
        <div className="userMenuWrap">
          <button type="button" className="userIconBtn" aria-label="用户菜单" title="用户菜单" onClick={onToggleUserMenu}>
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <circle cx="10" cy="7" r="3.2" />
              <path d="M4.5 16.5c.8-2.5 2.9-4 5.5-4s4.7 1.5 5.5 4" />
            </svg>
          </button>
          {userMenuOpen && (
            <div className="userMenu">
              <button type="button" onClick={onOpenUserSettings}>
                用户设置
              </button>
              <button type="button" onClick={onLogout}>
                登出
              </button>
            </div>
          )}
        </div>
        <span className="tag" title={roleText}>{displayName}</span>
      </div>
    </div>
  )
}
