import React from 'react'
import ReactMarkdown, { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

const components: Components = {
  h1: ({ node: _node, ...props }) => (
    <h1 className="mt-6 mb-3 text-xl font-bold tracking-tight text-slate-900 first:mt-0" {...props} />
  ),
  h2: ({ node: _node, ...props }) => (
    <h2 className="mt-6 mb-3 text-lg font-bold tracking-tight text-slate-900 first:mt-0" {...props} />
  ),
  h3: ({ node: _node, ...props }) => (
    <h3 className="mt-5 mb-2 text-base font-semibold text-slate-900 first:mt-0" {...props} />
  ),
  h4: ({ node: _node, ...props }) => (
    <h4 className="mt-4 mb-2 text-sm font-semibold text-slate-800 first:mt-0" {...props} />
  ),
  p: ({ node: _node, ...props }) => (
    <p className="my-2 text-sm leading-6 text-slate-700 first:mt-0 last:mb-0" {...props} />
  ),
  ul: ({ node: _node, ...props }) => (
    <ul className="my-3 list-disc space-y-1 pl-6 text-sm leading-6 text-slate-700" {...props} />
  ),
  ol: ({ node: _node, ...props }) => (
    <ol className="my-3 list-decimal space-y-1 pl-6 text-sm leading-6 text-slate-700" {...props} />
  ),
  li: ({ node: _node, ...props }) => <li className="pl-1" {...props} />,
  strong: ({ node: _node, ...props }) => (
    <strong className="font-semibold text-slate-900" {...props} />
  ),
  em: ({ node: _node, ...props }) => <em className="text-slate-700" {...props} />,
  blockquote: ({ node: _node, ...props }) => (
    <blockquote
      className="my-4 border-l-4 border-slate-300 bg-slate-50 px-4 py-2 text-slate-700"
      {...props}
    />
  ),
  hr: () => <hr className="my-6 border-slate-200" />,
  a: ({ node: _node, ...props }) => (
    <a
      className="font-medium text-blue-600 underline decoration-blue-200 underline-offset-2 hover:decoration-blue-500"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  code: ({ node: _node, className, children, ...props }) => {
    const inline = !className
    if (inline) {
      return (
        <code
          className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-800"
          {...props}
        >
          {children}
        </code>
      )
    }
    return (
      <code className={`font-mono text-xs text-slate-800 ${className || ''}`} {...props}>
        {children}
      </code>
    )
  },
  pre: ({ node: _node, ...props }) => (
    <pre
      className="my-4 overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-4"
      {...props}
    />
  ),
  table: ({ node: _node, ...props }) => (
    <div className="my-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full min-w-[640px] border-collapse text-left text-sm" {...props} />
    </div>
  ),
  thead: ({ node: _node, ...props }) => <thead className="bg-slate-100" {...props} />,
  tbody: ({ node: _node, ...props }) => (
    <tbody className="divide-y divide-slate-200" {...props} />
  ),
  tr: ({ node: _node, ...props }) => <tr className="align-top" {...props} />,
  th: ({ node: _node, ...props }) => (
    <th className="border-r border-slate-200 px-4 py-3 font-semibold text-slate-900 last:border-r-0" {...props} />
  ),
  td: ({ node: _node, ...props }) => (
    <td className="border-r border-slate-200 px-4 py-3 leading-5 text-slate-700 last:border-r-0" {...props} />
  ),
}

export default function AssignmentMarkdown({ content }: { content: string }) {
  return (
    <div className="min-w-0 max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
