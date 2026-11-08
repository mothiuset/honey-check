import { useElevation } from '@/presentation/shared/hooks/useElevation'
import { useOpenFolder } from '@/presentation/shared/hooks/useOpenFolder'
import { useStatusBar } from '../../hooks/useStatusBar'
import styles from './StatusBar.module.css'

/**
 * Barra de estado fija al pie: este equipo, el que se está viendo, los permisos, la tarea en curso y
 * la carpeta del análisis. El cuerpo reserva su alto, así que nunca tapa contenido.
 */
export function StatusBar() {
  const bar = useStatusBar()
  const { isElevated, requestElevation } = useElevation()
  const openFolder = useOpenFolder()

  return (
    <footer className={styles.bar} aria-label="Estado de Honey Check">
      <span className={styles.item} title={`Este equipo: ${bar.thisDevice}`}>
        <span className={styles.label}>Este equipo</span>
        <strong className={styles.name}>{bar.thisDevice}</strong>
        {!bar.viewing && bar.version ? (
          <span className={styles.pill}>{bar.version}</span>
        ) : null}
      </span>
      {bar.viewing ? (
        <span
          className={styles.item}
          data-tone="viewing"
          title={`Está viendo ${bar.viewing}`}
        >
          <span className={styles.label}>Viendo</span>
          <strong className={styles.name}>{bar.viewing}</strong>
          {bar.version ? (
            <span className={styles.pill}>{bar.version}</span>
          ) : null}
        </span>
      ) : null}
      {bar.task ? (
        <span className={styles.item} role="status">
          {bar.task}
        </span>
      ) : null}
      <span className={styles.item}>
        {isElevated ? (
          <>
            <span className={styles.dot} aria-hidden="true" />
            Administrador
          </>
        ) : (
          <button
            type="button"
            className={styles.link}
            onClick={requestElevation}
          >
            Ejecutar como administrador
          </button>
        )}
      </span>
      {bar.folder ? (
        <span className={styles.item} data-role="folder">
          <span className={styles.label}>Carpeta</span>
          <span className={styles.path} title={bar.folder}>
            {bar.folder}
          </span>
          <button
            type="button"
            className={styles.link}
            onClick={() => {
              openFolder(bar.folder ?? undefined)
            }}
          >
            Abrir
          </button>
        </span>
      ) : null}
    </footer>
  )
}
