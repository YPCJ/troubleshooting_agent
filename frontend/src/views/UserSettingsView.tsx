import type { Role } from '../types/app'
import { useState } from 'react'

export function UserSettingsView({
  role,
  username,
  onChangePassword,
}: {
  role: Role
  username: string
  onChangePassword: (payload: { currentPassword: string; newPassword: string }) => Promise<void>
}) {
  const [showPasswordModal, setShowPasswordModal] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const roleText = role === 'super_admin' ? '超级管理员' : role === 'admin' ? '管理员' : '普通用户'

  function openPasswordModal(): void {
    setShowPasswordModal(true)
    setError('')
  }

  function closePasswordModal(): void {
    setShowPasswordModal(false)
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setError('')
  }

  const canSubmit = Boolean(currentPassword) && newPassword.length >= 6 && newPassword === confirmPassword

  return (
    <div className="panel">
      <strong>用户设置</strong>
      <div className="settingsList">
        <div className="settingsRow">
          <span className="muted">账号</span>
          <span>{username}</span>
        </div>
        <div className="settingsRow">
          <span className="muted">角色</span>
          <span>{roleText}</span>
        </div>
        <div className="settingsRow">
          <span className="muted">密码</span>
          <button type="button" onClick={openPasswordModal}>修改密码</button>
        </div>
      </div>
      {error && <div className="errorText">{error}</div>}

      {showPasswordModal && (
        <div className="modalMask">
          <div className="modalCard">
            <div className="row between">
              <strong>修改密码</strong>
              <button type="button" onClick={closePasswordModal}>关闭</button>
            </div>
            <div className="grid2" style={{ marginTop: 10 }}>
              <div>
                <label>旧密码</label>
                <input type="password" value={currentPassword} placeholder="请输入旧密码" onChange={(e) => setCurrentPassword(e.target.value)} />
              </div>
              <div>
                <label>新密码</label>
                <input type="password" value={newPassword} placeholder="至少6位" onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              <div>
                <label>确认新密码</label>
                <input
                  type="password"
                  value={confirmPassword}
                  placeholder="再次输入新密码"
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </div>
            </div>
            {confirmPassword && newPassword !== confirmPassword && <div className="errorText">两次输入的新密码不一致</div>}
            {error && <div className="errorText">{error}</div>}
            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
              <button type="button" onClick={closePasswordModal}>取消</button>
              <button
                className="primary"
                type="button"
                disabled={!canSubmit || submitting}
                onClick={() => {
                  void (async () => {
                    setSubmitting(true)
                    setError('')
                    try {
                      await onChangePassword({ currentPassword, newPassword })
                      closePasswordModal()
                    } catch (e) {
                      const message = e instanceof Error ? e.message : '密码修改失败'
                      setError(message)
                    } finally {
                      setSubmitting(false)
                    }
                  })()
                }}
              >
                {submitting ? '提交中...' : '确认修改'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
