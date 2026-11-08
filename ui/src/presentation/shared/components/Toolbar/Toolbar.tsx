import type { ReactNode } from 'react'
import styles from './Toolbar.module.css'

/** Fila de controles o acciones que se reparte en varias líneas si no cabe. */
export function Toolbar({
  align = 'end',
  children,
}: {
  align?: 'end' | 'center'
  children: ReactNode
}) {
  return (
    <div className={styles.toolbar} data-align={align}>
      {children}
    </div>
  )
}
