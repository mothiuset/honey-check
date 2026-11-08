import { useState } from 'react'

/** Copia un texto al portapapeles y recuerda cuál fue el último copiado, para confirmarlo. */
export function useCopy() {
  const [copied, setCopied] = useState<string | null>(null)
  return {
    copied,
    copy: (text: string) => {
      void navigator.clipboard.writeText(text).then(
        () => {
          setCopied(text)
        },
        () => {
          setCopied(null)
        },
      )
    },
  }
}
