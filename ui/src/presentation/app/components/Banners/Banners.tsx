import { Button } from '@/presentation/shared/components'
import { useWorkspaceBanners } from '../../hooks/useWorkspaceBanners'
import styles from './Banners.module.css'

export function Banners() {
  const banners = useWorkspaceBanners()
  return (
    <>
      {banners.unavailable ? (
        <div className={styles.banner} data-tone="bad">
          La carpeta de Honey Check no está disponible. Si retiró la USB, vuelva
          a conectarla; los análisis nuevos quedarán en memoria hasta elegir
          otro destino.
        </div>
      ) : null}
      {banners.readOnly ? (
        <div className={styles.banner} data-tone="bad">
          La carpeta de Honey Check no permite escribir. Elija otro destino en
          Carpeta de datos.
        </div>
      ) : null}
      {banners.otherDevice ? (
        <div className={styles.banner} data-tone="other">
          <span>
            Está viendo <strong>{banners.otherDevice.name}</strong>, que no es
            este equipo (análisis del {banners.otherDevice.date}).
          </span>
          <Button size="small" onClick={banners.backToThisDevice}>
            Volver a este equipo
          </Button>
        </div>
      ) : null}
    </>
  )
}
