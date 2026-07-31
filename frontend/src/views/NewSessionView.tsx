import type { AppCard, ModelProfile } from '../types/app'

export function NewSessionView({
  selectedApp,
  onChangeApp,
  sessionTitle,
  onChangeSessionTitle,
  apps,
  modelProfiles,
  selectedModelProfile,
  onChangeModelProfile,
  onCreate,
  creating,
}: {
  selectedApp: string
  onChangeApp: (id: string) => void
  sessionTitle: string
  onChangeSessionTitle: (value: string) => void
  apps: AppCard[]
  modelProfiles: ModelProfile[]
  selectedModelProfile: string
  onChangeModelProfile: (id: string) => void
  onCreate: () => void
  creating: boolean
}) {
  return (
    <div className="panel">
      <strong>新建 Session</strong>
      <div className="grid2">
        <div>
          <label>App 选择</label>
          <select value={selectedApp} onChange={(e) => onChangeApp(e.target.value)}>
            {apps.map((app) => (
              <option key={app.id} value={app.id}>
                {app.id}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>模型</label>
          <select value={selectedModelProfile} onChange={(e) => onChangeModelProfile(e.target.value)}>
            {modelProfiles.length === 0 && <option value="gemini_default">gemini_default</option>}
            {modelProfiles.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id} ({item.provider} / {item.modelName})
              </option>
            ))}
          </select>
        </div>
      </div>
      <label>会话名称（可选）</label>
      <input
        value={sessionTitle}
        placeholder="不填则默认：App名称 + 日期 + 时间"
        onChange={(e) => onChangeSessionTitle(e.target.value)}
      />
      <label>任务输入</label>
      <textarea rows={4} placeholder="输入任务描述" />
      <div className="row">
        <input placeholder="可选：文件路径（非必填）" />
        <button type="button">上传文件（可选）</button>
      </div>
      <button className="primary" type="button" onClick={onCreate} disabled={creating}>
        {creating ? '启动中...' : '启动会话'}
      </button>
    </div>
  )
}
