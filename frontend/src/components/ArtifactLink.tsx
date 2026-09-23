import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { fetchArtifactContent } from '../api/service'
import type { ArtifactItem } from '../types/app'
import { MarkdownContent } from './MarkdownContent'

type Props = {
  token: string
  artifact: ArtifactItem
}

function renderTextWindow(
  popup: Window,
  artifact: ArtifactItem,
  content: string,
  markdown: boolean,
) {
  popup.document.title = artifact.name
  popup.document.head.innerHTML = ''
  const style = popup.document.createElement('style')
  style.textContent = `
    body { margin: 0; background: #0f172a; color: #e2e8f0; font: 15px/1.65 system-ui, sans-serif; }
    main { box-sizing: border-box; max-width: 980px; min-height: 100vh; margin: 0 auto; padding: 36px 44px; }
    h1, h2, h3 { color: #f8fafc; line-height: 1.3; }
    a { color: #93c5fd; }
    code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    code { background: #1e293b; border-radius: 4px; padding: 0.1em 0.3em; }
    pre { overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: #111827; border: 1px solid #334155; border-radius: 8px; padding: 14px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #334155; padding: 7px 9px; text-align: left; }
    blockquote { margin-left: 0; border-left: 3px solid #60a5fa; padding-left: 14px; color: #cbd5e1; }
    .mermaidBlock { margin: 18px 0; overflow: auto; border: 1px solid #334155; border-radius: 10px; background: #fff; padding: 18px; }
    .mermaidSvg { min-width: max-content; text-align: center; }
    .mermaidSvg svg { display: block; max-width: none; height: auto; margin: 0 auto; }
    .mermaidLoading, .mermaidError { color: #94a3b8; }
    .mermaidFallback { margin-top: 12px; }
  `
  popup.document.head.appendChild(style)
  popup.document.body.innerHTML = ''
  const container = popup.document.createElement('main')
  popup.document.body.appendChild(container)
  const root = createRoot(container)
  root.render(
    markdown ? (
      <MarkdownContent content={content} />
    ) : (
      <pre>{content}</pre>
    ),
  )
}

export function ArtifactLink({ token, artifact }: Props) {
  const [error, setError] = useState('')

  const openArtifact = async () => {
    setError('')
    const popup = window.open('', '_blank')
    if (!popup) {
      setError('浏览器阻止了新标签页，请允许弹窗后重试')
      return
    }
    popup.opener = null
    popup.document.title = `正在打开 ${artifact.name}`
    popup.document.body.textContent = '正在加载文件…'

    try {
      const { blob, contentType } = await fetchArtifactContent(token, artifact)
      const lowerName = artifact.name.toLowerCase()
      const isMarkdown =
        lowerName.endsWith('.md') ||
        lowerName.endsWith('.markdown') ||
        contentType.includes('text/markdown')
      const isText =
        isMarkdown ||
        contentType.startsWith('text/') ||
        contentType.includes('json') ||
        lowerName.endsWith('.json') ||
        lowerName.endsWith('.csv')
      if (isText) {
        renderTextWindow(popup, artifact, await blob.text(), isMarkdown)
        return
      }
      const objectUrl = URL.createObjectURL(blob)
      popup.location.replace(objectUrl)
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : '文件打开失败'
      setError(message)
      popup.document.body.textContent = `文件打开失败：${message}`
    }
  }

  return (
    <div>
      <button type="button" className="artifactOpenButton" onClick={() => void openArtifact()}>
        <span className="artifactName">{artifact.name}</span>
        <span className="artifactPath">{artifact.path}</span>
        <span className="artifactOpenHint">在新标签页中打开 ↗</span>
      </button>
      {error && <div className="errorText">{error}</div>}
    </div>
  )
}
