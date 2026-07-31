import type { Role } from '../types/app'

export function ToolsView({ role }: { role: Role }) {
  const editable = role === 'admin' || role === 'super_admin'

  return (
    <div className="panel">
      <div className="row between">
        <strong>Tools 管理</strong>
        <div className="row">
          <button type="button" disabled={!editable}>
            新增 Tool
          </button>
          <button type="button" disabled={!editable}>
            删除 Tool
          </button>
        </div>
      </div>
      <ul>
        <li>bash(command)</li>
        <li>read_file(path)</li>
        <li>data_query(sat_id, para_name, start_time, end_time)</li>
      </ul>
    </div>
  )
}
