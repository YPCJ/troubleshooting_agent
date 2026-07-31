import type { AppCard } from '../types/app'

export function AppsView({ apps, onChoose }: { apps: AppCard[]; onChoose: (appId: string) => void }) {
  return (
    <div className="panel">
      <strong>智能体 / 应用列表</strong>
      <p className="muted">点击卡片进入新建 Session，并自动带入 App。</p>
      <div className="appGrid">
        {apps.map((app) => (
          <button key={app.id} type="button" className="appCard" onClick={() => onChoose(app.id)}>
            <span className="icon">{app.icon}</span>
            <strong>{app.id}</strong>
            <span className="muted">{app.desc}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
