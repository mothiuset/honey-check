import type { DevicePage } from '@/application'
import { Button, Field } from '@/presentation/shared/components'
import styles from './DevicePager.module.css'

const SIZES = [25, 50, 100, 200]

export interface DevicePagerProps {
  readonly page: DevicePage
  readonly size: number
  readonly onPage: (page: number) => void
  readonly onSize: (size: number) => void
}

export function DevicePager({ page, size, onPage, onSize }: DevicePagerProps) {
  return (
    <nav className={styles.pager} aria-label="Páginas de equipos">
      <Button
        size="small"
        disabled={page.page <= 1}
        onClick={() => {
          onPage(page.page - 1)
        }}
      >
        Anterior
      </Button>
      <span>
        Página {page.page} de {page.pages}
      </span>
      <Button
        size="small"
        disabled={page.page >= page.pages}
        onClick={() => {
          onPage(page.page + 1)
        }}
      >
        Siguiente
      </Button>
      <Field label="Por página">
        <select
          value={size}
          onChange={(event) => {
            onSize(Number(event.target.value))
          }}
        >
          {SIZES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </Field>
    </nav>
  )
}
