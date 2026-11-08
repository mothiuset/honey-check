import type { ReactNode } from 'react'
import styles from './Notice.module.css'

export interface NoticeProps {
  readonly tone?: 'info' | 'bad'
  readonly children: ReactNode
}

/** Aviso dentro del contenido: qué pasó y, al lado, la acción que lo resuelve. */
export function Notice({ tone = 'info', children }: NoticeProps) {
  return (
    <div className={styles.notice} data-tone={tone}>
      {children}
    </div>
  )
}
