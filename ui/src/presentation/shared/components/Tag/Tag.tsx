import type { ReactNode } from 'react'
import styles from './Tag.module.css'

export type TagTone = 'neutral' | 'honey' | 'ok' | 'bad'

/** Insignia corta junto a un dato: «este equipo», «referencia», «verificado», «SSD NVMe». */
export function Tag({
  tone = 'neutral',
  title,
  children,
}: {
  tone?: TagTone
  title?: string | undefined
  children: ReactNode
}) {
  return (
    <span className={styles.tag} data-tone={tone} title={title}>
      {children}
    </span>
  )
}
