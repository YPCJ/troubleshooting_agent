import { useEffect, useMemo, useRef, useState } from 'react'
import type { ModelCapabilities, ModelParameterCapability, ModelProfile } from '../types/app'

type Provider = string
type SamplingMode = 'provider_default' | 'stable' | 'flexible' | 'custom'
type OutputMode = 'provider_default' | 'custom_limit'
type VerbosityMode = 'provider_default' | 'low' | 'medium' | 'high'

type ConnectionTestResult = {
  ok: boolean
  provider: string
  modelName: string
  response: string
  latencyMs: number
  usage: {
    promptTokens?: number
    completionTokens?: number
    totalTokens?: number
  }
}

type Draft = {
  profileId: string
  provider: Provider
  modelName: string
  baseUrl: string
  temperature: string
  topP: string
  topK: string
  maxOutputTokens: string
  samplingMode: SamplingMode
  outputMode: OutputMode
  verbosity: VerbosityMode
  samplingStrategy: 'temperature' | 'top_p'
}

function toDraft(profile?: ModelProfile): Draft {
  return {
    profileId: profile?.id ?? '',
    provider: profile?.provider || 'aliyun',
    modelName: profile?.modelName ?? '',
    baseUrl: profile?.baseUrl ?? '',
    temperature: profile?.temperature == null ? '' : String(profile.temperature),
    topP: profile?.topP == null ? '' : String(profile.topP),
    topK: profile?.topK == null ? '' : String(profile.topK),
    maxOutputTokens: profile?.maxOutputTokens == null ? '' : String(profile.maxOutputTokens),
    samplingMode: profile?.samplingMode
      ?? (profile && [profile.temperature, profile.topP, profile.topK].some((value) => value != null) ? 'custom' : 'provider_default'),
    outputMode: profile?.outputMode
      ?? (profile?.maxOutputTokens == null ? 'provider_default' : 'custom_limit'),
    verbosity: profile?.verbosity ?? 'provider_default',
    samplingStrategy: profile?.topP != null && profile?.temperature == null ? 'top_p' : 'temperature',
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
  onTestConnection,
  onGetCapabilities,
  providerModels,
  providers,
  onCreateProvider,
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
    samplingMode: SamplingMode
    outputMode: OutputMode
    verbosity: Exclude<VerbosityMode, 'provider_default'> | null
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
    samplingMode: SamplingMode
    outputMode: OutputMode
    verbosity: Exclude<VerbosityMode, 'provider_default'> | null
    temperature?: number
    topP?: number
    topK?: number
    maxOutputTokens?: number
  }) => void
  onSetDefault: (profileId: string) => void
  onDelete: (profileId: string) => Promise<boolean>
  onTestConnection: (payload: {
    profileId?: string
    provider?: Provider
    modelName?: string
    baseUrl?: string
  }) => Promise<ConnectionTestResult>
  onGetCapabilities: (payload: { provider: string; modelName: string; profileId?: string }) => Promise<ModelCapabilities>
  providerModels: string[]
  providers: string[]
  onCreateProvider: (payload: { id: string; displayName: string; baseUrl: string; apiKeyEnv: string }) => Promise<void>
  catalogQuery: string
  onCatalogQueryChange: (value: string) => void
  onCatalogProviderChange: (value: Provider) => void
  catalogLoading: boolean
  loading: boolean
  error: string
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [cloneSourceId, setCloneSourceId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(toDraft())
  const [connectionStatus, setConnectionStatus] = useState('')
  const [testingConnection, setTestingConnection] = useState(false)
  const [capabilities, setCapabilities] = useState<ModelCapabilities | null>(null)
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(false)
  const [capabilitiesError, setCapabilitiesError] = useState('')
  const capabilitiesCache = useRef(new Map<string, ModelCapabilities>())
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [showProviderCreate, setShowProviderCreate] = useState(false)
  const [providerDraft, setProviderDraft] = useState({ id: '', displayName: '', baseUrl: '', apiKeyEnv: '' })
  const [providerCreateError, setProviderCreateError] = useState('')
  const [providerCreating, setProviderCreating] = useState(false)

  const editingProfile = useMemo(() => profiles.find((item) => item.id === editingId) ?? null, [profiles, editingId])

  useEffect(() => {
    const modelName = draft.modelName.trim()
    if ((!showCreate && !editingProfile) || !modelName) {
      setCapabilities(null)
      setCapabilitiesLoading(false)
      setCapabilitiesError('')
      return
    }
    const profileId = showCreate ? undefined : editingProfile?.id
    const cacheKey = `${draft.provider}\u0000${modelName}\u0000${profileId ?? ''}`
    const cached = capabilitiesCache.current.get(cacheKey)
    if (cached) {
      setCapabilities(cached)
      setCapabilitiesLoading(false)
      setCapabilitiesError('')
      return
    }
    let active = true
    setCapabilities(null)
    setCapabilitiesLoading(true)
    setCapabilitiesError('')
    const loadCapabilities = () => {
      void onGetCapabilities({
        provider: draft.provider,
        modelName,
        profileId,
      }).then((result) => {
        if (active) {
          capabilitiesCache.current.set(cacheKey, result)
          setCapabilities(result)
        }
      }).catch((error: unknown) => {
        if (active) {
          setCapabilities(null)
          setCapabilitiesError(error instanceof Error ? error.message : '模型能力读取失败')
        }
      }).finally(() => {
        if (active) setCapabilitiesLoading(false)
      })
    }
    // Existing entries already have a stable model name, so load immediately.
    // Debounce only while a user is typing a new model name.
    const timer = showCreate ? window.setTimeout(loadCapabilities, 300) : null
    if (!showCreate) loadCapabilities()
    return () => {
      active = false
      if (timer != null) window.clearTimeout(timer)
    }
  }, [draft.modelName, draft.provider, editingProfile, onGetCapabilities, showCreate])

  const openEdit = (profile: ModelProfile) => {
    const cacheKey = `${profile.provider}\u0000${profile.modelName.trim()}\u0000${profile.id}`
    const cached = capabilitiesCache.current.get(cacheKey) ?? null
    setEditingId(profile.id)
    setShowCreate(false)
    setCloneSourceId(null)
    setDraft(toDraft(profile))
    setCapabilities(cached)
    setCapabilitiesLoading(!cached)
    setCapabilitiesError('')
    setAdvancedOpen(profile.samplingMode === 'custom' || (!profile.samplingMode && [profile.temperature, profile.topP, profile.topK].some((value) => value != null)))
    setConnectionStatus('')
    onCatalogQueryChange('')
    onCatalogProviderChange(profile.provider)
  }

  const openCreate = () => {
    setEditingId(null)
    setShowCreate(true)
    setCloneSourceId(null)
    setDraft(toDraft())
    setCapabilities(null)
    setCapabilitiesLoading(false)
    setCapabilitiesError('')
    setAdvancedOpen(false)
    setConnectionStatus('')
    onCatalogQueryChange('')
    onCatalogProviderChange('aliyun')
  }

  const closeModal = () => {
    setEditingId(null)
    setShowCreate(false)
    setCloneSourceId(null)
    setCapabilities(null)
    setCapabilitiesLoading(false)
    setCapabilitiesError('')
    setConnectionStatus('')
  }

  const openClone = (profile: ModelProfile) => {
    const cacheKey = `${profile.provider}\u0000${profile.modelName.trim()}\u0000`
    const cached = capabilitiesCache.current.get(cacheKey) ?? null
    setEditingId(null)
    setShowCreate(true)
    setCloneSourceId(profile.id)
    setDraft({ ...toDraft(profile), profileId: '' })
    setCapabilities(cached)
    setCapabilitiesLoading(!cached)
    setCapabilitiesError('')
    setAdvancedOpen(profile.samplingMode === 'custom' || (!profile.samplingMode && [profile.temperature, profile.topP, profile.topK].some((value) => value != null)))
    setConnectionStatus('')
    onCatalogQueryChange('')
    onCatalogProviderChange(profile.provider)
  }

  const submit = () => {
    const preset = capabilities?.samplingPresets.find((item) => item.id === draft.samplingMode)
    const presetTemperature = preset?.temperature ?? toOptionalNumber(draft.temperature)
    const presetTopP = preset?.topP ?? toOptionalNumber(draft.topP)
    const samplingPayload = {
      profileId: draft.profileId,
      samplingMode: draft.samplingMode,
      outputMode: draft.outputMode,
      verbosity: draft.verbosity === 'provider_default' ? null : draft.verbosity,
      temperature: draft.samplingMode === 'custom'
        ? (draft.samplingStrategy === 'temperature' ? toOptionalNumber(draft.temperature) : undefined)
        : draft.samplingMode === 'provider_default' ? undefined : presetTemperature,
      topP: draft.samplingMode === 'custom'
        ? (draft.samplingStrategy === 'top_p' ? toOptionalNumber(draft.topP) : undefined)
        : draft.samplingMode === 'provider_default' ? undefined : presetTopP,
      topK: draft.samplingMode === 'custom' ? toOptionalNumber(draft.topK) : undefined,
      maxOutputTokens: draft.outputMode === 'custom_limit' ? toOptionalNumber(draft.maxOutputTokens) : undefined,
    }
    if (showCreate) {
      onCreate({
        ...samplingPayload,
        provider: draft.provider,
        modelName: draft.modelName,
        baseUrl: draft.baseUrl || undefined,
      })
    } else {
      onSave(samplingPayload)
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

  const handleTestConnection = () => {
    void (async () => {
      setTestingConnection(true)
      setConnectionStatus('')
      try {
        const result = await onTestConnection(
          showCreate
            ? {
                provider: draft.provider,
                modelName: draft.modelName,
                baseUrl: draft.baseUrl || undefined,
              }
            : { profileId: editingProfile?.id },
        )
        const tokenText = result.usage.totalTokens == null ? 'Token 用量未返回' : `共 ${result.usage.totalTokens} Token`
        setConnectionStatus(`调用成功：${result.response}（耗时 ${result.latencyMs} ms，${tokenText}）`)
      } catch (error) {
        setConnectionStatus(error instanceof Error ? `调用失败：${error.message}` : '调用失败')
      } finally {
        setTestingConnection(false)
      }
    })()
  }

  const modelCountText = catalogLoading
    ? '正在加载模型列表...'
    : `检索到 ${providerModels.length} 个当前接口可发现模型`

  const parameter = (name: 'temperature' | 'top_p' | 'top_k' | 'max_output_tokens'): ModelParameterCapability | undefined =>
    capabilities?.parameters[name]

  const defaultLabel = (name: 'temperature' | 'top_p' | 'top_k' | 'max_output_tokens') => {
    const value = parameter(name)?.default
    return value == null ? '模型默认' : `模型默认 ${value}`
  }

  const samplingTunable = capabilities == null
    ? true
    : ['temperature', 'top_p', 'top_k'].some((name) => parameter(name as 'temperature' | 'top_p' | 'top_k')?.supported)

  const selectSamplingMode = (mode: SamplingMode) => {
    if (mode === 'provider_default') {
      setDraft((prev) => ({ ...prev, samplingMode: mode, temperature: '', topP: '', topK: '' }))
      setAdvancedOpen(false)
      return
    }
    const preset = capabilities?.samplingPresets.find((item) => item.id === mode)
    if (preset) {
      setDraft((prev) => ({
        ...prev,
        samplingMode: mode,
        samplingStrategy: preset.topP != null && preset.temperature == null ? 'top_p' : 'temperature',
        temperature: preset.temperature == null ? '' : String(preset.temperature),
        topP: preset.topP == null ? '' : String(preset.topP),
        topK: '',
      }))
      setAdvancedOpen(false)
      return
    }
    const useTemperature = parameter('temperature')?.supported !== false
    setDraft((prev) => ({
      ...prev,
      samplingMode: 'custom',
      samplingStrategy: useTemperature ? 'temperature' : 'top_p',
      temperature: useTemperature && !prev.temperature
        ? String(parameter('temperature')?.default ?? 0.7)
        : prev.temperature,
      topP: !useTemperature && !prev.topP
        ? String(parameter('top_p')?.default ?? 0.95)
        : prev.topP,
    }))
    setAdvancedOpen(true)
  }

  const resetGenerationSettings = () => {
    setDraft((prev) => ({
      ...prev,
      samplingMode: 'provider_default',
      outputMode: 'provider_default',
      verbosity: 'provider_default',
      temperature: '',
      topP: '',
      topK: '',
      maxOutputTokens: '',
    }))
    setAdvancedOpen(false)
  }

  const samplingSummary = (() => {
    if (draft.samplingMode === 'provider_default') return '模型推荐'
    if (draft.samplingMode === 'stable') return `稳定${draft.temperature ? ` · Temperature ${draft.temperature}` : ''}`
    if (draft.samplingMode === 'flexible') return `灵活${draft.temperature ? ` · Temperature ${draft.temperature}` : ''}`
    const parts = [
      draft.samplingStrategy === 'temperature' && draft.temperature ? `Temperature ${draft.temperature}` : '',
      draft.samplingStrategy === 'top_p' && draft.topP ? `Top-P ${draft.topP}` : '',
      draft.topK ? `Top-K ${draft.topK}` : '',
    ].filter(Boolean)
    return parts.length ? `自定义 · ${parts.join(' · ')}` : '自定义'
  })()

  const verbositySummary = draft.verbosity === 'provider_default'
    ? '模型推荐'
    : ({ low: '简洁', medium: '标准', high: '详细' } as const)[draft.verbosity]
  const outputSummary = draft.outputMode === 'custom_limit' && draft.maxOutputTokens
    ? `${draft.maxOutputTokens} Token 上限`
    : draft.outputMode === 'custom_limit' ? '待设置 Token 上限' : '模型推荐'
  const customSamplingValue = draft.samplingStrategy === 'temperature'
    ? toOptionalNumber(draft.temperature)
    : toOptionalNumber(draft.topP)
  const customOutputValue = toOptionalNumber(draft.maxOutputTokens)
  const modelOutputMaximum = parameter('max_output_tokens')?.max
  const generationSettingsInvalid = (
    draft.samplingMode === 'custom' && customSamplingValue == null
  ) || (
    draft.outputMode === 'custom_limit'
    && (customOutputValue == null || customOutputValue < 1 || (modelOutputMaximum != null && customOutputValue > modelOutputMaximum))
  )

  const applyProviderChange = (provider: Provider) => {
    const currentProvider = draft.provider
    if (!showCreate || currentProvider === provider) return
    setDraft((prev) => ({ ...prev, provider, baseUrl: '' }))
    setCapabilities(null)
    setCapabilitiesLoading(Boolean(draft.modelName.trim()))
    setCapabilitiesError('')
    onCatalogQueryChange('')
    onCatalogProviderChange(provider)
  }

  return (
    <div className="panel">
      <div className="row between">
        <strong>模型管理（管理员）</strong>
        <div className="row">
          <button type="button" onClick={() => setShowProviderCreate((value) => !value)}>新增服务商连接</button>
          <button type="button" className="primary" onClick={openCreate}>新建模型入口</button>
        </div>
      </div>
      {error && <div className="errorBanner">{error}</div>}
      <p className="muted">每个模型入口都是独立模块；创建后基础参数只读，仅生成设置可编辑。</p>

      {showProviderCreate && (
        <form className="modalSection" onSubmit={(event) => {
          event.preventDefault()
          setProviderCreateError('')
          setProviderCreating(true)
          void onCreateProvider(providerDraft).then(() => {
            const providerId = providerDraft.id.trim().toLowerCase()
            setShowProviderCreate(false)
            setProviderDraft({ id: '', displayName: '', baseUrl: '', apiKeyEnv: '' })
            setEditingId(null)
            setShowCreate(true)
            setDraft({ ...toDraft(), provider: providerId })
            onCatalogProviderChange(providerId)
          }).catch((cause: unknown) => {
            setProviderCreateError(cause instanceof Error ? cause.message : '创建服务商连接失败')
          }).finally(() => setProviderCreating(false))
        }}>
          <strong>新增 OpenAI Chat 兼容服务商</strong>
          <p className="muted">连接创建后，可在“新建模型入口”中选择它。API Key 由后端环境变量读取，不会保存到模型配置中。</p>
          <div className="modelPropertyGrid">
            <label>连接 ID<input required value={providerDraft.id} placeholder="例如 deepseek" onChange={(event) => setProviderDraft((prev) => ({ ...prev, id: event.target.value }))} /></label>
            <label>显示名称<input required value={providerDraft.displayName} placeholder="例如 DeepSeek" onChange={(event) => setProviderDraft((prev) => ({ ...prev, displayName: event.target.value }))} /></label>
            <label>API 根地址<input required type="url" value={providerDraft.baseUrl} placeholder="https://api.example.com/v1" onChange={(event) => setProviderDraft((prev) => ({ ...prev, baseUrl: event.target.value }))} /></label>
            <label>API Key 环境变量<input required value={providerDraft.apiKeyEnv} placeholder="例如 DEEPSEEK_API_KEY" onChange={(event) => setProviderDraft((prev) => ({ ...prev, apiKeyEnv: event.target.value }))} /></label>
          </div>
          {providerCreateError && <div className="errorBanner">{providerCreateError}</div>}
          <div className="row"><button type="submit" className="primary" disabled={providerCreating}>{providerCreating ? '正在创建...' : '创建连接'}</button></div>
        </form>
      )}

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
              <strong>
                {showCreate
                  ? cloneSourceId
                    ? `复制模型入口：${cloneSourceId}`
                    : '新建模型入口'
                  : `编辑模型入口：${editingProfile?.id}`}
              </strong>
              <button type="button" onClick={closeModal}>关闭</button>
            </div>

            {showCreate && (
              <>
                <div className="row" style={{ marginTop: 8 }}>
                  <input value={catalogQuery} onChange={(e) => onCatalogQueryChange(e.target.value)} placeholder="搜索模型名" />
                  <button
                    type="button"
                    disabled={!providerModels[0]}
                    onClick={() => {
                      setDraft((prev) => ({ ...prev, modelName: providerModels[0] }))
                      setCapabilities(null)
                      setCapabilitiesLoading(true)
                      setCapabilitiesError('')
                    }}
                  >
                    用首个匹配
                  </button>
                </div>
                <div className="muted">{modelCountText}</div>
              </>
            )}

            <div className="modalSection">
              <strong>基础参数</strong>
              {showCreate ? (
                <div className="grid2" style={{ marginTop: 10 }}>
                  <div>
                    <label>profile_id</label>
                    <input
                      value={draft.profileId}
                      onChange={(e) => setDraft((prev) => ({ ...prev, profileId: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label>provider</label>
                    <select value={draft.provider} onChange={(e) => applyProviderChange(e.target.value)}>
                      {providers.map((provider) => (
                        <option key={provider} value={provider}>{provider}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label>model_name</label>
                    <input
                      value={draft.modelName}
                      list="model-catalog-list"
                      onChange={(e) => {
                        setDraft((prev) => ({ ...prev, modelName: e.target.value }))
                        setCapabilities(null)
                        setCapabilitiesLoading(Boolean(e.target.value.trim()))
                        setCapabilitiesError('')
                      }}
                    />
                    <datalist id="model-catalog-list">
                      {providerModels.map((name) => (
                        <option key={name} value={name} />
                      ))}
                    </datalist>
                  </div>
                  {['aliyun', 'gemini', 'openai'].includes(draft.provider) ? (
                    <div>
                      <label>base_url（可选）</label>
                      <input value={draft.baseUrl} onChange={(e) => setDraft((prev) => ({ ...prev, baseUrl: e.target.value }))} />
                    </div>
                  ) : (
                    <div className="muted">API 地址与密钥由服务商连接统一管理</div>
                  )}
                </div>
              ) : (
                <>
                  <div className="muted">基础参数创建后不可修改；如需调整，请复制为新入口。</div>
                  <dl className="modelPropertyGrid">
                    <div>
                      <dt>profile_id</dt>
                      <dd>{draft.profileId}</dd>
                    </div>
                    <div>
                      <dt>provider</dt>
                      <dd>{draft.provider}</dd>
                    </div>
                    <div>
                      <dt>model_name</dt>
                      <dd>{draft.modelName}</dd>
                    </div>
                    <div>
                      <dt>base_url</dt>
                      <dd>{draft.baseUrl || '使用服务商连接地址'}</dd>
                    </div>
                  </dl>
                </>
              )}
            </div>

            <div className="modalSection">
              <div className="generationSettingsHeader">
                <div>
                  <strong>生成设置</strong>
                  <p>只向模型服务发送这里明确覆盖的设置。</p>
                </div>
                <div className="row">
                  {capabilitiesLoading && <span className="muted">正在读取模型能力...</span>}
                  <button type="button" className="resetSettingsButton" disabled={capabilitiesLoading} onClick={resetGenerationSettings}>恢复推荐设置</button>
                </div>
              </div>

              {capabilitiesLoading && !capabilities ? (
                <div className="generationSettingsCard capabilitySkeleton" aria-busy="true" aria-label="正在读取模型能力">
                  <section className="settingBlock">
                    <span className="skeletonLine skeletonLineShort" />
                    <span className="skeletonLine skeletonLineMedium" />
                    <div className="skeletonChoiceGrid">
                      <span /><span /><span /><span />
                    </div>
                  </section>
                  <section className="settingBlock">
                    <span className="skeletonLine skeletonLineShort" />
                    <div className="skeletonPillRow"><span /><span /></div>
                  </section>
                  <section className="settingBlock">
                    <span className="skeletonLine skeletonLineShort" />
                    <div className="skeletonPillRow"><span /><span /></div>
                  </section>
                </div>
              ) : (
                <>
                  {capabilitiesError && (
                    <div className="capabilityLoadError">模型能力读取失败，当前仅显示通用设置：{capabilitiesError}</div>
                  )}
                  <div className="generationSettingsCard">
                <section className="settingBlock">
                  <div className="settingHeader">
                    <div>
                      <strong>回答风格</strong>
                      <span>先选用途，系统再映射为模型支持的采样参数</span>
                    </div>
                  </div>
                  <div className="choicePills" role="group" aria-label="回答风格">
                    <button type="button" className={draft.samplingMode === 'provider_default' ? 'active' : ''} aria-pressed={draft.samplingMode === 'provider_default'} onClick={() => selectSamplingMode('provider_default')}>
                      <strong>模型推荐</strong><small>不覆盖采样参数</small>
                    </button>
                    {capabilities?.samplingPresets.some((item) => item.id === 'stable') && (
                      <button type="button" className={draft.samplingMode === 'stable' ? 'active' : ''} aria-pressed={draft.samplingMode === 'stable'} onClick={() => selectSamplingMode('stable')}>
                        <strong>稳定</strong><small>结果更一致，适合结构化任务</small>
                      </button>
                    )}
                    {capabilities?.samplingPresets.some((item) => item.id === 'flexible') && (
                      <button type="button" className={draft.samplingMode === 'flexible' ? 'active' : ''} aria-pressed={draft.samplingMode === 'flexible'} onClick={() => selectSamplingMode('flexible')}>
                        <strong>灵活</strong><small>增加变化，适合探索与表达</small>
                      </button>
                    )}
                    {samplingTunable && (
                      <button type="button" className={draft.samplingMode === 'custom' ? 'active' : ''} aria-pressed={draft.samplingMode === 'custom'} onClick={() => selectSamplingMode('custom')}>
                        <strong>自定义</strong><small>精确控制底层采样参数</small>
                      </button>
                    )}
                  </div>
                  {capabilities?.recommendProviderDefaults && (
                    <div className="capabilityNotice">当前模型会自行管理采样，建议保留“模型推荐”。</div>
                  )}
                </section>

                {capabilities?.verbosity.supported && (
                  <section className="settingBlock">
                    <div className="settingHeader">
                      <div><strong>回答详略</strong><span>控制回答展开程度，不等同于输出 Token 上限</span></div>
                    </div>
                    <div className="compactChoicePills" role="group" aria-label="回答详略">
                      {([
                        ['provider_default', '模型推荐'],
                        ['low', '简洁'],
                        ['medium', '标准'],
                        ['high', '详细'],
                      ] as const).filter(([value]) => value === 'provider_default' || capabilities.verbosity.choices.includes(value)).map(([value, label]) => (
                        <button key={value} type="button" className={draft.verbosity === value ? 'active' : ''} aria-pressed={draft.verbosity === value} onClick={() => setDraft((prev) => ({ ...prev, verbosity: value }))}>{label}</button>
                      ))}
                    </div>
                  </section>
                )}

                <section className="settingBlock">
                  <div className="settingHeader">
                    <div><strong>输出预算</strong><span>这是硬上限，并不是期望的回答长度</span></div>
                    {parameter('max_output_tokens')?.max != null && <em>模型上限 {parameter('max_output_tokens')?.max}</em>}
                  </div>
                  <div className="outputBudgetEditor">
                    <div className="compactChoicePills" role="group" aria-label="输出预算模式">
                      <button type="button" className={draft.outputMode === 'provider_default' ? 'active' : ''} aria-pressed={draft.outputMode === 'provider_default'} onClick={() => setDraft((prev) => ({ ...prev, outputMode: 'provider_default', maxOutputTokens: '' }))}>模型推荐</button>
                      <button type="button" className={draft.outputMode === 'custom_limit' ? 'active' : ''} aria-pressed={draft.outputMode === 'custom_limit'} onClick={() => setDraft((prev) => ({ ...prev, outputMode: 'custom_limit' }))}>设置上限</button>
                    </div>
                    {draft.outputMode === 'custom_limit' && (
                      <label className="outputLimitInput">
                        <input
                          type="number"
                          min={parameter('max_output_tokens')?.min ?? 1}
                          max={parameter('max_output_tokens')?.max ?? undefined}
                          placeholder="例如 4096"
                          value={draft.maxOutputTokens}
                          onChange={(event) => setDraft((prev) => ({ ...prev, maxOutputTokens: event.target.value }))}
                        />
                        <span>Token</span>
                      </label>
                    )}
                  </div>
                  {capabilities?.output.countsReasoningTokens && <p className="settingFootnote">推理模型的内部思考 Token 也可能占用这项预算。</p>}
                </section>

                {samplingTunable && (
                  <details className="advancedGeneration" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
                    <summary>高级采样参数 <span>仅在需要复现实验或精确调参时使用</span></summary>
                    <div className="advancedGenerationBody">
                      <div className="row between">
                        <label>采样算法</label>
                        <div className="samplingTabs">
                          {parameter('temperature')?.supported !== false && (
                            <button type="button" className={draft.samplingStrategy === 'temperature' ? 'active' : ''} onClick={() => setDraft((prev) => ({ ...prev, samplingMode: 'custom', samplingStrategy: 'temperature', temperature: prev.temperature || String(parameter('temperature')?.default ?? 0.7) }))}>Temperature</button>
                          )}
                          {parameter('top_p')?.supported !== false && (
                            <button type="button" className={draft.samplingStrategy === 'top_p' ? 'active' : ''} onClick={() => setDraft((prev) => ({ ...prev, samplingMode: 'custom', samplingStrategy: 'top_p', topP: prev.topP || String(parameter('top_p')?.default ?? 0.95) }))}>Top-P</button>
                          )}
                        </div>
                      </div>
                      {draft.samplingStrategy === 'temperature' ? (
                        <div className="rangeRow">
                          <input type="range" min={parameter('temperature')?.min ?? 0} max={parameter('temperature')?.max ?? 2} step={parameter('temperature')?.step ?? 0.1} value={draft.temperature || parameter('temperature')?.default || 0.7} onChange={(event) => setDraft((prev) => ({ ...prev, samplingMode: 'custom', temperature: event.target.value }))} />
                          <input className="compactNumber" type="number" min={parameter('temperature')?.min ?? 0} max={parameter('temperature')?.max ?? 2} step={parameter('temperature')?.step ?? 0.1} value={draft.temperature} placeholder={defaultLabel('temperature')} onChange={(event) => setDraft((prev) => ({ ...prev, samplingMode: 'custom', temperature: event.target.value }))} />
                        </div>
                      ) : (
                        <div className="rangeRow">
                          <input type="range" min={parameter('top_p')?.min ?? 0} max={parameter('top_p')?.max ?? 1} step={parameter('top_p')?.step ?? 0.05} value={draft.topP || parameter('top_p')?.default || 0.95} onChange={(event) => setDraft((prev) => ({ ...prev, samplingMode: 'custom', topP: event.target.value }))} />
                          <input className="compactNumber" type="number" min={parameter('top_p')?.min ?? 0} max={parameter('top_p')?.max ?? 1} step={parameter('top_p')?.step ?? 0.05} value={draft.topP} placeholder={defaultLabel('top_p')} onChange={(event) => setDraft((prev) => ({ ...prev, samplingMode: 'custom', topP: event.target.value }))} />
                        </div>
                      )}
                      {parameter('top_k')?.supported && (
                        <div className="advancedInlineField">
                          <label>Top-K <span>{defaultLabel('top_k')}</span></label>
                          <input type="number" min={parameter('top_k')?.min ?? 1} max={parameter('top_k')?.max ?? undefined} value={draft.topK} placeholder="留空则不覆盖" onChange={(event) => setDraft((prev) => ({ ...prev, samplingMode: 'custom', topK: event.target.value }))} />
                        </div>
                      )}
                      <p className="settingFootnote">Temperature 与 Top-P 二选一；更改这里会自动切换为“自定义”。</p>
                    </div>
                  </details>
                )}
                  </div>

                  <div className="effectiveConfigBar">
                    <strong>实际配置</strong>
                    <span>回答风格：{samplingSummary}</span>
                    {capabilities?.verbosity.supported && <span>回答详略：{verbositySummary}</span>}
                    <span>输出预算：{outputSummary}</span>
                  </div>
                </>
              )}
            </div>

            {connectionStatus && <div className="muted" style={{ marginTop: 8 }}>{connectionStatus}</div>}

            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10, gap: 8 }}>
              {!showCreate && editingProfile && (
                <>
                  <button type="button" onClick={handleSetDefault} disabled={defaultProfileId === editingProfile.id}>
                    {defaultProfileId === editingProfile.id ? '已是默认' : '设为默认'}
                  </button>
                  <button type="button" onClick={() => openClone(editingProfile)} disabled={loading}>
                    复制为新入口
                  </button>
                  <button type="button" onClick={handleDelete} disabled={loading} style={{ color: '#b91c1c' }}>
                    删除入口
                  </button>
                </>
              )}
              <button type="button" onClick={handleTestConnection} disabled={loading || testingConnection || !draft.modelName.trim()}>
                {testingConnection ? '正在调用...' : '测试模型调用'}
              </button>
              <button type="button" onClick={closeModal}>取消</button>
              <button className="primary" type="button" disabled={loading || capabilitiesLoading || generationSettingsInvalid || !draft.profileId.trim() || !draft.modelName.trim()} onClick={submit}>
                {showCreate ? '创建' : '保存生成参数'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
