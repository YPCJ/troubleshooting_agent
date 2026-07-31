import type { UserAccount } from '../api/service'
import { useState } from 'react'
import type { Role } from '../types/app'

export function UsersView({
  users,
  loading,
  error,
  currentRole,
  currentUsername,
  onRefresh,
  onCreateUser,
  onDeleteUser,
  onResetPassword,
}: {
  users: UserAccount[]
  loading: boolean
  error: string
  currentRole: Role
  currentUsername: string
  onRefresh: () => void
  onCreateUser: (payload: { username: string; password: string; role: 'admin' | 'user' }) => Promise<void>
  onDeleteUser: (username: string) => Promise<void>
  onResetPassword: (payload: { username: string; newPassword: string }) => Promise<void>
}) {
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showResetModal, setShowResetModal] = useState(false)
  const [targetUser, setTargetUser] = useState<UserAccount | null>(null)
  const [modalSubmitting, setModalSubmitting] = useState(false)
  const [modalError, setModalError] = useState('')
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('')
  const [newRole, setNewRole] = useState<'admin' | 'user'>('user')
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [resetPassword, setResetPassword] = useState('')
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState('')
  const canCreateAdmin = currentRole === 'super_admin'

  function canDelete(item: UserAccount): boolean {
    if (item.username === currentUsername) return false
    if (item.role === 'super_admin') return false
    if (currentRole === 'super_admin') return item.role === 'admin' || item.role === 'user'
    if (currentRole === 'admin') return item.role === 'user'
    return false
  }

  function canResetPassword(item: UserAccount): boolean {
    if (item.username === currentUsername) return false
    return canDelete(item)
  }

  function roleText(role: UserAccount['role']): string {
    if (role === 'super_admin') return '超级管理员'
    if (role === 'admin') return '管理员'
    return '普通用户'
  }

  function openCreateModal(): void {
    setModalError('')
    setShowCreateModal(true)
  }

  function closeCreateModal(): void {
    setShowCreateModal(false)
    setNewUsername('')
    setNewPassword('')
    setNewPasswordConfirm('')
    setNewRole('user')
    setModalError('')
  }

  function openDeleteModal(item: UserAccount): void {
    setTargetUser(item)
    setDeleteConfirmText('')
    setModalError('')
    setShowDeleteModal(true)
  }

  function closeDeleteModal(): void {
    setShowDeleteModal(false)
    setTargetUser(null)
    setDeleteConfirmText('')
    setModalError('')
  }

  function openResetModal(item: UserAccount): void {
    setTargetUser(item)
    setResetPassword('')
    setResetPasswordConfirm('')
    setModalError('')
    setShowResetModal(true)
  }

  function closeResetModal(): void {
    setShowResetModal(false)
    setTargetUser(null)
    setResetPassword('')
    setResetPasswordConfirm('')
    setModalError('')
  }

  const canSubmitCreate = Boolean(newUsername.trim()) && newPassword.length >= 6 && newPassword === newPasswordConfirm
  const canSubmitDelete = Boolean(targetUser) && deleteConfirmText.trim() === targetUser?.username
  const canSubmitReset = Boolean(targetUser) && resetPassword.length >= 6 && resetPassword === resetPasswordConfirm

  return (
    <div className="panel">
      <div className="row between">
        <strong>用户管理（管理员与超级管理员）</strong>
        <div className="row">
          <button type="button" onClick={openCreateModal}>新建用户</button>
          <button type="button" onClick={onRefresh}>刷新</button>
        </div>
      </div>
      {loading && <div className="muted">加载中...</div>}
      {!loading && error && <div className="errorText">{error}</div>}
      {!loading && !error && (
        <table className="usersTable">
          <thead>
            <tr>
              <th>用户名</th>
              <th>角色</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((item) => (
              <tr key={item.username}>
                <td>{item.username}{item.username === currentUsername ? '（当前）' : ''}</td>
                <td>{roleText(item.role)}</td>
                <td>{item.isDisabled ? '已禁用' : '正常'}</td>
                <td>{item.createdAt}</td>
                <td>{item.updatedAt}</td>
                <td>
                  <div className="row">
                    <button type="button" onClick={() => openResetModal(item)} disabled={!canResetPassword(item)}>
                      重置密码
                    </button>
                    <button type="button" onClick={() => openDeleteModal(item)} disabled={!canDelete(item)}>
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showCreateModal && (
        <div className="modalMask">
          <div className="modalCard">
            <div className="row between">
              <strong>新建用户</strong>
              <button type="button" onClick={closeCreateModal}>关闭</button>
            </div>
            <div className="grid2" style={{ marginTop: 10 }}>
              <div>
                <label>用户名</label>
                <input value={newUsername} placeholder="用户名（3-32位）" onChange={(e) => setNewUsername(e.target.value)} />
              </div>
              <div>
                <label>角色</label>
                <select value={newRole} onChange={(e) => setNewRole(e.target.value as 'admin' | 'user')}>
                  <option value="user">普通用户</option>
                  {canCreateAdmin && <option value="admin">管理员</option>}
                </select>
              </div>
              <div>
                <label>初始密码</label>
                <input value={newPassword} type="password" placeholder="至少6位" onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              <div>
                <label>确认初始密码</label>
                <input value={newPasswordConfirm} type="password" placeholder="再次输入密码" onChange={(e) => setNewPasswordConfirm(e.target.value)} />
              </div>
            </div>
            {newPasswordConfirm && newPassword !== newPasswordConfirm && <div className="errorText">两次输入的密码不一致</div>}
            {modalError && <div className="errorText">{modalError}</div>}
            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
              <button type="button" onClick={closeCreateModal}>取消</button>
              <button
                className="primary"
                type="button"
                disabled={!canSubmitCreate || modalSubmitting}
                onClick={() => {
                  void (async () => {
                    setModalSubmitting(true)
                    setModalError('')
                    try {
                      await onCreateUser({ username: newUsername.trim(), password: newPassword, role: newRole })
                      closeCreateModal()
                    } catch (error) {
                      const message = error instanceof Error ? error.message : '创建用户失败'
                      setModalError(message)
                    } finally {
                      setModalSubmitting(false)
                    }
                  })()
                }}
              >
                {modalSubmitting ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showDeleteModal && targetUser && (
        <div className="modalMask">
          <div className="modalCard">
            <div className="row between">
              <strong>确认删除用户</strong>
              <button type="button" onClick={closeDeleteModal}>关闭</button>
            </div>
            <p className="muted" style={{ marginTop: 10 }}>
              为避免误操作，请输入用户名 <strong>{targetUser.username}</strong> 进行确认。
            </p>
            <input
              style={{ marginTop: 8 }}
              value={deleteConfirmText}
              placeholder="输入用户名确认删除"
              onChange={(e) => setDeleteConfirmText(e.target.value)}
            />
            {modalError && <div className="errorText">{modalError}</div>}
            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
              <button type="button" onClick={closeDeleteModal}>取消</button>
              <button
                className="primary"
                type="button"
                disabled={!canSubmitDelete || modalSubmitting}
                onClick={() => {
                  void (async () => {
                    setModalSubmitting(true)
                    setModalError('')
                    try {
                      await onDeleteUser(targetUser.username)
                      closeDeleteModal()
                    } catch (error) {
                      const message = error instanceof Error ? error.message : '删除用户失败'
                      setModalError(message)
                    } finally {
                      setModalSubmitting(false)
                    }
                  })()
                }}
              >
                {modalSubmitting ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showResetModal && targetUser && (
        <div className="modalMask">
          <div className="modalCard">
            <div className="row between">
              <strong>重置用户密码：{targetUser.username}</strong>
              <button type="button" onClick={closeResetModal}>关闭</button>
            </div>
            <div className="grid2" style={{ marginTop: 10 }}>
              <div>
                <label>新密码</label>
                <input value={resetPassword} type="password" placeholder="至少6位" onChange={(e) => setResetPassword(e.target.value)} />
              </div>
              <div>
                <label>确认新密码</label>
                <input
                  value={resetPasswordConfirm}
                  type="password"
                  placeholder="再次输入新密码"
                  onChange={(e) => setResetPasswordConfirm(e.target.value)}
                />
              </div>
            </div>
            {resetPasswordConfirm && resetPassword !== resetPasswordConfirm && <div className="errorText">两次输入的密码不一致</div>}
            {modalError && <div className="errorText">{modalError}</div>}
            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
              <button type="button" onClick={closeResetModal}>取消</button>
              <button
                className="primary"
                type="button"
                disabled={!canSubmitReset || modalSubmitting}
                onClick={() => {
                  void (async () => {
                    setModalSubmitting(true)
                    setModalError('')
                    try {
                      await onResetPassword({ username: targetUser.username, newPassword: resetPassword })
                      closeResetModal()
                    } catch (error) {
                      const message = error instanceof Error ? error.message : '重置密码失败'
                      setModalError(message)
                    } finally {
                      setModalSubmitting(false)
                    }
                  })()
                }}
              >
                {modalSubmitting ? '提交中...' : '确认重置'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
