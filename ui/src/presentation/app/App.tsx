import { Button, Copyable, Lede } from '@/presentation/shared/components'
import styles from './App.module.css'
import { ActionLayer } from '@/presentation/support/components/ActionLayer/ActionLayer'
import { Banners } from './components/Banners/Banners'
import { ConfirmDialog } from './components/ConfirmDialog/ConfirmDialog'
import { CurrentPage, MAIN_ID } from './components/CurrentPage/CurrentPage'
import { NavMenu } from './components/NavMenu/NavMenu'
import { RailHeader } from './components/RailHeader/RailHeader'
import { StatusBar } from './components/StatusBar/StatusBar'
import { useAppStartup } from './hooks/useAppStartup'
import { useExit } from './hooks/useExit'
import { useMenu } from './hooks/useMenu'

/** Armazón: riel de navegación (barra compacta con menú en pantallas estrechas), contenido y estado. */
export function App() {
  const { ready, stopped, appVersion } = useAppStartup()
  const menu = useMenu()
  const exit = useExit()

  if (stopped) return <p className={styles.goodbye}>{stopped}</p>

  return (
    <>
      <a className={styles.skip} href={`#${MAIN_ID}`}>
        Saltar al contenido
      </a>
      <div className={styles.shell}>
        <header
          ref={menu.container}
          className={styles.rail}
          data-open={menu.open}
        >
          <RailHeader menuOpen={menu.open} onToggleMenu={menu.toggle} />
          <div id="rail-menu" className={styles.menu}>
            <NavMenu />
            <div className={styles.foot}>
              {/* Versión, número de compilación (siempre sube), commit y fecha: con un clic se copia
                  para comparar con la última publicada. */}
              <span className={styles.version}>
                <Copyable text={appVersion}>Versión {appVersion}</Copyable>
              </span>
              <Button
                size="small"
                tone="ghost"
                className={styles.exit}
                onClick={exit}
              >
                Salir de Honey Check
              </Button>
            </div>
          </div>
        </header>
        <div className={styles.workspace}>
          <Banners />
          <main id={MAIN_ID} tabIndex={-1} className={styles.main}>
            {ready ? <CurrentPage /> : <Lede live>Cargando Honey Check.</Lede>}
          </main>
        </div>
      </div>
      <StatusBar />
      <ConfirmDialog />
      {/* Acciones de Soporte que corren sin salir de la pantalla: panel lateral y avisos. */}
      <ActionLayer />
    </>
  )
}
