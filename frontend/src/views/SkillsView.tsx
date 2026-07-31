import type { SkillItem } from '../types/app'

export function SkillsView({
  skills,
  selectedSkillId,
  markdown,
  onSelectSkill,
  onChangeMarkdown,
  onSaveVersion,
  loading,
  error,
}: {
  skills: SkillItem[]
  selectedSkillId: string
  markdown: string
  onSelectSkill: (skillId: string) => void
  onChangeMarkdown: (value: string) => void
  onSaveVersion: () => void
  loading: boolean
  error: string
}) {
  return (
    <div className="panel">
      <strong>Skills 管理</strong>
      <p className="muted">普通用户可编辑 Markdown；管理员可增删启停。</p>
      {loading && <div className="muted">加载中...</div>}
      {!loading && error && <div className="errorText">{error}</div>}
      <div className="grid2">
        <ul>
          {skills.map((item) => (
            <li key={item.id}>
              <button type="button" className={item.id === selectedSkillId ? 'ghost activeSkill' : 'ghost'} onClick={() => onSelectSkill(item.id)}>
                {item.id}
              </button>
            </li>
          ))}
        </ul>
        <div>
          <textarea rows={8} value={markdown} onChange={(e) => onChangeMarkdown(e.target.value)} />
          <div className="row">
            <button className="primary" type="button" onClick={onSaveVersion}>
              保存新版本
            </button>
            <button type="button">查看历史版本</button>
          </div>
        </div>
      </div>
    </div>
  )
}
