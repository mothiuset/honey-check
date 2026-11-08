import type { ReactNode } from 'react'
import styles from './Text.module.css'

/** Texto de apoyo bajo un título: estado, conteos o explicación breve. */
export function Lede({
  children,
  live = false,
}: {
  children: ReactNode
  live?: boolean
}) {
  return (
    <p className={styles.lede} role={live ? 'status' : undefined}>
      {children}
    </p>
  )
}

/** Ruta o comando, en monoespaciada y partible en cualquier punto. */
export function PathText({
  children,
  title,
}: {
  children: ReactNode
  title?: string | undefined
}) {
  return (
    <span className={styles.path} title={title}>
      {children}
    </span>
  )
}

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className={styles.hidden}>{children}</span>
}
