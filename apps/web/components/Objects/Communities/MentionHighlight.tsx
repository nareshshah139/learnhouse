import React from 'react'
import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

const mentionPattern = () => /(?<![\w@/])@[\w](?:[\w.-]*[\w])?/g
const mentionClass = 'text-blue-700 bg-blue-50 rounded px-0.5 font-medium'

export function MentionText({ text }: { text: string }) {
  // Preserve plain text and never interpret user content as HTML.
  const fragments: React.ReactNode[] = []
  let offset = 0
  for (const match of text.matchAll(/```[\s\S]*?```|`[^`]*`|(?<![\w@/])@[\w](?:[\w.-]*[\w])?/g)) {
    fragments.push(text.slice(offset, match.index))
    fragments.push(match[0].startsWith('@')
      ? <span className={mentionClass} key={match.index}>{match[0]}</span> : match[0])
    offset = match.index + match[0].length
  }
  fragments.push(text.slice(offset))
  return <>{fragments}</>
}

export const MentionHighlight = Extension.create({
  name: 'mentionHighlight',
  addProseMirrorPlugins() {
    return [new Plugin({
      key: new PluginKey('mentionHighlight'),
      props: {
        decorations(state) {
          const decorations: Decoration[] = []
          state.doc.descendants((node, pos, parent) => {
            if (!node.isText || !node.text || parent?.type.name === 'codeBlock' || node.marks.some(mark => mark.type.name === 'code')) return
            for (const match of node.text.matchAll(mentionPattern())) {
              decorations.push(Decoration.inline(pos + match.index, pos + match.index + match[0].length, { class: mentionClass }))
            }
          })
          return DecorationSet.create(state.doc, decorations)
        },
      },
    })]
  },
})
