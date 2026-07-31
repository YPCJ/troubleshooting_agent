import { useMemo, useState } from 'react'
import type { ModelProfile } from '../types/app'

type Provider = 'aliyun' | 'gemini'

type Draft = {
  profileId: string
  provider: Provider
  modelName: string
  baseUrl: string
  temperature: string
  topP: string
  topK: string
  maxOutputTokens: string
}

function toDraft(profile?: ModelProfile): Draft {
  return {
    profileId: profile?.id ?? '',
    provider: profile?.provider === 'gemini' ? 'gemini' : 'aliyun',
    modelName: profile?.modelName ?? '',
    baseUrl: profile?.baseUrl ?? '',
    temperature: profile?.temperature == null ? '' : String(profile.temperature),
    topP: profile?.topP == null ? '' : String(profile.topP),
    topK: profile?.topK == null ? '' : String(profile.topK),
    maxOutputTokens: profile?.maxOutputTokens == null ? '' : String(profile.maxOutputTokens),
  }
}

function toOptionalNumber(value: string): number | undefined {
  const v = value.trim()
  if (!v) return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

export function ModelsView({
  profiles,
  defaultProfileId,
  onSave,
  onCreate,
  onSetDefault,
  onDelete,
  providerModels,
  catalogQuery,
  onCatalogQueryChange,
  onCatalogProviderChange,
  catalogLoading,
  loading,
  error,
}: {
  profiles: ModelProfile[]
  defaultProfileId: string
  onSave: (payload: {
    profileId: string
    provider: Provider
    modelName: string
    baseUrl?: string
    temperature?: number
    topP?: number
    topK?: number
    maxOutputTokens?: number
  }) => void
  onCreate: (payload: {
    profileId: string
    provider: Provider
    modelName: string
    baseUrl?: string
    temperature?: number
    topP?: number
    topK?: number
    maxOutputTokens?: number
  }) => void
  onSetDefault: (profileId: string) => void
  onDelete: (profileId: string) => Promise<boolean>
  providerModels: string[]
  catalogQuery: string
  onCatalogQueryChange: (value: string) => void
  onCatalogProviderChange: (value: Provider) => void
  catalogLoading: boolean
  loading: boolean
  error: string
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [draft, setDraft] = useState<Draft>(toDraft())

  const editingProfile = useMemo(() => profiles.find((item) => item.id === editingId) ?? null, [profiles, editingId])

  const openEdit = (profile: ModelProfile) => {
    setEditingId(profile.id)
    setShowCreate(false)
    setDraft(toDraft(profile))
    onCatalogProviderChange(profile.provider === 'gemini' ? 'gemini' : 'aliyun')
  }

  const openCreate = () => {
    setEditingId(null)
    setShowCreate(true)
    setDraft(toDraft())
    onCatalogProviderChange('aliyun')
  }

  const closeModal = () => {
    setEditingId(null)
    setShowCreate(false)
  }

  const submit = () => {
    const payload = {
      profileId: draft.profileId,
      provider: draft.provider,
      modelName: draft.modelName,
      baseUrl: draft.baseUrl || undefined,
      temperature: toOptionalNumber(draft.temperature),
      topP: toOptionalNumber(draft.topP),
      topK: toOptionalNumber(draft.topK),
      maxOutputTokens: toOptionalNumber(draft.maxOutputTokens),
    }
    if (showCreate) {
      onCreate(payload)
    } else {
      onSave(payload)
    }
    closeModal()
  }

  const handleDelete = () => {
    if (!editingProfile) return
    if (!window.confirm(`确认删除模型入口 “${editingProfile.id}” 吗？`)) return
    void (async () => {
      const deleted = await onDelete(editingProfile.id)
      if (deleted) closeModal()
    })()
  }

  const handleSetDefault = () => {
    if (!editingProfile) return
    if (defaultProfileId === editingProfile.id) return
    onSetDefault(editingProfile.id)
  }

  const modelCountText = catalogLoading ? '正在加载模型列表...' : `检索到 ${providerModels.length} 个模型`

  const applyProviderChange = (provider: Provider) => {
    const currentProvider = draft.provider
    if (
      !showCreate &&
      editingProfile &&
      currentProvider !== provider &&
      !window.confirm('修改 provider 可能导致当前模型名或调用参数不再兼容，确认继续吗？')
    ) {
      return
    }
    setDraft((prev) => ({ ...prev, provider }))
    onCatalogProviderChange(provider)
  }

  return (
    <div className="panel">
      <div className="row between">
        <strong>模型管理（管理员）</strong>
        <button type="button" className="primary" onClick={openCreate}>
          新建模型入口
        </button>
      </div>
      {error && <div className="errorBanner">{error}</div>}
      <p className="muted">每个模型入口都是独立模块，点击后弹窗查看和编辑详细参数。</p>

      <div className="appGrid">
        {profiles.map((profile) => {
          const isDefault = defaultProfileId === profile.id
          return (
            <button key={profile.id} type="button" className="appCard" onClick={() => openEdit(profile)}>
              <span className="icon">🤖</span>
              <strong>{profile.id}</strong>
              <span className="muted">{profile.provider} / {profile.modelName}</span>
              {isDefault ? <span className="muted">默认入口</span> : <span className="muted">可选入口</span>}
            </button>
          )
        })}
      </div>

      {(showCreate || editingProfile) && (
        <div className="modalMask">
          <div className="modalCard">
            <div className="row between">
              <strong>{showCreate ? '新建模型入口' : `编辑模型入口：${editingProfile?.id}`}</strong>
              <button type="button" onClick={closeModal}>关闭</button>
            </div>

            <div className="row" style={{ marginTop: 8 }}>
              <input value={catalogQuery} onChange={(e) => onCatalogQueryChange(e.target.value)} placeholder="搜索模型名" />
              <button
                type="button"
                disabled={!providerModels[0]}
                onClick={() => {
                  setDraft((prev) => ({ ...prev, modelName: providerModels[0] }))
                }}
              >
                用首个匹配
              </button>
            </div>
            <div className="muted">{modelCountText}</div>

            <div className="modalSection">
              <strong>基础参数</strong>
              <div className="grid2" style={{ marginTop: 10 }}>
                <div>
                <label>profile_id</label>
                <input
                  value={draft.profileId}
                  disabled={!showCreate}
                  onChange={(e) => setDraft((prev) => ({ ...prev, profileId: e.target.value }))}
                />
                </div>
                <div>
                  <label>provider</label>
                  <select value={draft.provider} onChange={(e) => applyProviderChange(e.target.value as Provider)}>
                    <option value="aliyun">aliyun</option>
                    <option value="gemini">gemini</option>
                  </select>
                </div>
                <div>
                  <label>model_name</label>
                  <input
                    value={draft.modelName}
                    list="model-catalog-list"
                    onChange={(e) => setDraft((prev) => ({ ...prev, modelName: e.target.value }))}
                  />
                  <datalist id="model-catalog-list">
                    {providerModels.map((name) => (
                      <option key={name} value={name} />
                    ))}
                  </datalist>
                </div>
                <div>
                  <label>base_url（可选）</label>
                  <input value={draft.baseUrl} onChange={(e) => setDraft((prev) => ({ ...prev, baseUrl: e.target.value }))} />
                </div>
              </div>
            </div>

            <div className="modalSection">
              <strong>采样参数</strong>
              <div className="grid2" style={{ marginTop: 10 }}>
                <div>
                  <label>temperature</label>
                  <input value={draft.temperature} onChange={(e) => setDraft((prev) => ({ ...prev, temperature: e.target.value }))} />
                </div>
                <div>
                  <label>top_p（或 top_n）</label>
                  <input value={draft.topP} onChange={(e) => setDraft((prev) => ({ ...prev, topP: e.target.value }))} />
                </div>
                <div>
                  <label>top_k</label>
                  <input value={draft.topK} onChange={(e) => setDraft((prev) => ({ ...prev, topK: e.target.value }))} />
                </div>
                <div>
                  <label>max_output_tokens</label>
                  <input value={draft.maxOutputTokens} onChange={(e) => setDraft((prev) => ({ ...prev, maxOutputTokens: e.target.value }))} />
                </div>
              </div>
            </div>

            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10, gap: 8 }}>
              {!showCreate && editingProfile && (
                <>
                  <button type="button" onClick={handleSetDefault} disabled={defaultProfileId === editingProfile.id}>
                    {defaultProfileId === editingProfile.id ? '已是默认' : '设为默认'}
                  </button>
                  <button type="button" onClick={handleDelete} disabled={loading} style={{ color: '#b91c1c' }}>
                    删除入口
                  </button>
                </>
              )}
              <button type="button" onClick={closeModal}>取消</button>
              <button className="primary" type="button" disabled={loading} onClick={submit}>
                {showCreate ? '创建' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
