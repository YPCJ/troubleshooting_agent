import type { ArtifactItem } from '../types/app'

export function ResultsView({
  artifacts,
  filter,
  searchSessionId,
  onChangeFilter,
  onChangeSearchSessionId,
  onSearch,
  loading,
  error,
}: {
  artifacts: ArtifactItem[]
  filter: 'all' | 'doc' | 'image' | 'data'
  searchSessionId: string
  onChangeFilter: (value: 'all' | 'doc' | 'image' | 'data') => void
  onChangeSearchSessionId: (value: string) => void
  onSearch: () => void
  loading: boolean
  error: string
}) {
  return (
    <div className="panel">
      <strong>结果中心</strong>
      <div className="row">
        <select value={filter} onChange={(e) => onChangeFilter(e.target.value as 'all' | 'doc' | 'image' | 'data')}>
          <option value="all">全部类型</option>
          <option value="doc">Markdown</option>
          <option value="image">Image</option>
          <option value="data">JSON</option>
        </select>
        <input placeholder="按 Session ID 检索" value={searchSessionId} onChange={(e) => onChangeSearchSessionId(e.target.value)} />
        <button type="button" onClick={onSearch}>
          搜索
        </button>
      </div>
      {loading && <div className="muted">加载中...</div>}
      {!loading && error && <div className="errorText">{error}</div>}
      {!loading && !error && (
        <ul>
          {artifacts.map((item) => (
            <li key={item.id}>
              [{item.artifactType}] {item.name}
              <div className="artifactPath">{item.path}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
