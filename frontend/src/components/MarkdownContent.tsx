import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import mermaid from 'mermaid'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'loose',
  theme: 'base',
  themeVariables: {
    primaryColor: '#0f172a',
    primaryTextColor: '#e2e8f0',
    primaryBorderColor: '#334155',
    lineColor: '#64748b',
    secondaryColor: '#111827',
    tertiaryColor: '#1e293b',
  },
})

type MarkdownCodeProps = {
  className?: string
  inline?: boolean
  children?: ReactNode
}

function MermaidBlock({ chart }: { chart: string }) {
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const idRef = useRef(`mermaid-${Math.random().toString(36).slice(2)}`)

  useEffect(() => {
    let cancelled = false
    setError(null)
    setSvg(null)

    void (async () => {
      try {
        const rendered = await mermaid.render(idRef.current, chart)
        if (!cancelled) setSvg(rendered.svg)
      } catch (cause) {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : '流程图渲染失败')
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [chart])

  return (
    <div className="mermaidBlock">
      {error ? (
        <div>
          <div className="mermaidError">流程图渲染失败：{error}</div>
          <pre className="mermaidFallback">{chart}</pre>
        </div>
      ) : svg ? (
        <div className="mermaidSvg" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="mermaidLoading">正在渲染流程图…</div>
      )}
    </div>
  )
}

export function MarkdownContent({ content }: { content: string }) {
  const components = useMemo(
    () => ({
      code: ({ className, inline, children }: MarkdownCodeProps) => {
        const text = String(children).replace(/\n$/, '')
        const languageMatch = className?.match(/language-(\w+)/)
        const language = languageMatch?.[1]
        const isBlock = Boolean(language) || text.includes('\n') || inline === false
        if (language === 'mermaid') return <MermaidBlock chart={text} />
        if (!isBlock) return <code className={className}>{children}</code>
        return (
          <pre>
            <code className={className}>{text}</code>
          </pre>
        )
      },
    }),
    [],
  )

  return (
    <div className="mdContent">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
