import { useMemo, useState } from 'react'
import type { Role, ToolItem } from '../types/app'

const CATEGORY_ORDER: Array<ToolItem['category']> = ['file', 'shell', 'data', 'skills', 'sbc', 'other']

const CATEGORY_LABELS: Record<ToolItem['category'], string> = {
  file: '文件类',
  shell: 'Shell 类',
  data: '数据类',
  skills: 'Skills 类',
  sbc: '天基承载网类',
  other: '其他类',
}

const CATEGORY_ICONS: Record<ToolItem['category'], string> = {
  file: '📁',
  shell: '⌘',
  data: '🗄',
  skills: '📘',
  sbc: '🛰',
  other: '🧩',
}

function groupTools(tools: ToolItem[]): Record<ToolItem['category'], ToolItem[]> {
  const grouped = {
    file: [],
    shell: [],
    data: [],
    skills: [],
    sbc: [],
    other: [],
  } as Record<ToolItem['category'], ToolItem[]>
  for (const tool of tools) {
    // A category the frontend does not know about must not crash the whole view,
    // so anything unrecognised is folded into "other".
    const bucket = grouped[tool.category] ? tool.category : 'other'
    grouped[bucket].push(tool)
  }
  return grouped
}

export function ToolsView({
  role,
  tools,
  loading,
  error,
  onToggleEnabled,
}: {
  role: Role
  tools: ToolItem[]
  loading: boolean
  error: string
  onToggleEnabled: (tool: ToolItem, enabled: boolean) => void
}) {
  const editable = role === 'admin' || role === 'super_admin'
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all')

  const stats = useMemo(
    () => ({
      total: tools.length,
      enabled: tools.filter((item) => item.enabled).length,
      unavailable: tools.filter((item) => !item.available).length,
    }),
    [tools],
  )

  const visibleTools = useMemo(() => {
    const needle = keyword.trim().toLowerCase()
    return tools.filter((tool) => {
      if (statusFilter === 'enabled' && !tool.enabled) return false
      if (statusFilter === 'disabled' && tool.enabled) return false
      if (!needle) return true
      return (
        tool.name.toLowerCase().includes(needle) ||
        tool.description.toLowerCase().includes(needle) ||
        tool.apps.some((app) => app.toLowerCase().includes(needle))
      )
    })
  }, [tools, keyword, statusFilter])

  const grouped = groupTools(visibleTools)
  const hasVisibleTools = visibleTools.length > 0

  return (
    <div className="panel toolsPanel">
      <div className="toolsHeader">
        <div>
          <strong>Tools 管理</strong>
          <div className="muted">按类目分组展示，支持启用/禁用内置工具</div>
        </div>
        <div className="toolsStats">
          <span className="toolsStat">
            <b>{stats.total}</b> 总数
          </span>
          <span className="toolsStat toolsStat--on">
            <b>{stats.enabled}</b> 已启用
          </span>
          {stats.unavailable > 0 && (
            <span className="toolsStat toolsStat--warn">
              <b>{stats.unavailable}</b> 不可用
            </span>
          )}
        </div>
      </div>

      {!loading && !error && (
        <div className="toolsFilters">
          <input
            className="toolsSearch"
            type="search"
            value={keyword}
            placeholder="搜索工具名称、描述或所属应用"
            onChange={(e) => setKeyword(e.target.value)}
          />
          <div className="toolsSegment">
            {(
              [
                ['all', '全部'],
                ['enabled', '已启用'],
                ['disabled', '已禁用'],
              ] as Array<[typeof statusFilter, string]>
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={statusFilter === value ? 'toolsSegmentBtn is-active' : 'toolsSegmentBtn'}
                onClick={() => setStatusFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <div className="muted">加载中...</div>}
      {!loading && error && <div className="errorText">{error}</div>}

      {!loading && !error && !hasVisibleTools && (
        <div className="toolsEmpty">没有符合条件的工具，试试调整搜索词或筛选条件。</div>
      )}

      {!loading && !error && hasVisibleTools && (
        <div className="toolsGroups">
          {CATEGORY_ORDER.map((category) => {
            const items = grouped[category]
            if (items.length === 0) return null
            return (
              <section key={category} className="toolsGroup">
                <header className="toolsGroupHead">
                  <span className="toolsGroupIcon" aria-hidden="true">
                    {CATEGORY_ICONS[category]}
                  </span>
                  <span className="toolsGroupTitle">{CATEGORY_LABELS[category]}</span>
                  <span className="toolsGroupCount">{items.length}</span>
                </header>
                <div className="toolsGrid">
                  {items.map((tool) => (
                    <article key={tool.name} className={tool.enabled ? 'toolCard is-enabled' : 'toolCard'}>
                      <div className="toolCardTop">
                        <h4 className="toolCardName" title={tool.name}>
                          {tool.name}
                        </h4>
                        <label className="toolSwitch" title={editable ? '' : '需要管理员权限'}>
                          <input
                            type="checkbox"
                            checked={tool.enabled}
                            disabled={!editable}
                            onChange={(e) => onToggleEnabled(tool, e.target.checked)}
                          />
                          <span className="toolSwitchTrack" aria-hidden="true" />
                        </label>
                      </div>
                      <p className="toolCardDesc">{tool.description || '暂无描述'}</p>
                      <div className="toolCardFoot">
                        {!tool.available && (
                          <span className="tag tag--warn" title="该工具没有绑定实现，启用后仍无法调用">
                            不可用
                          </span>
                        )}
                        {tool.apps.length > 0 ? (
                          tool.apps.map((app) => (
                            <span key={app} className="tag">
                              {app}
                            </span>
                          ))
                        ) : (
                          <span className="tag tag--ghost">未标注应用</span>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
