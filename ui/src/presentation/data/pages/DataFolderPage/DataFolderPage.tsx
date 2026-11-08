import {
  Button,
  LinkButton,
  Notice,
  PathText,
  SpecList,
  Toolbar,
} from '@/presentation/shared/components'
import { READING_GUIDE } from '../../formatters/dataFolderText'
import { useDataFolder } from '../../hooks/useDataFolder'

export function DataFolderPage() {
  const data = useDataFolder()
  return (
    <>
      <h1>Carpeta de datos</h1>
      {data.pending ? (
        <Notice tone="bad">
          <p>
            El último análisis no se pudo guardar. Sigue en memoria hasta que
            elija un destino o cierre Honey Check.
          </p>
          <input
            type="text"
            value={data.directory}
            placeholder="Ejemplo: C:\Inventarios"
            aria-label="Carpeta donde guardar el inventario"
            onChange={(event) => {
              data.setDirectory(event.target.value)
            }}
          />
          <Button onClick={data.save}>Guardar en esta carpeta</Button>
          <LinkButton href={data.pendingDownloadUrl} download>
            Descargar con el navegador
          </LinkButton>
          {data.feedback ? <p role="status">{data.feedback}</p> : null}
        </Notice>
      ) : null}
      <SpecList rows={data.rows} />
      <Toolbar align="center">
        <Button onClick={data.openDataFolder}>Abrir la carpeta de datos</Button>
        {data.currentDownloadUrl ? (
          <LinkButton href={data.currentDownloadUrl} download>
            Descargar el JSON que está viendo
          </LinkButton>
        ) : null}
      </Toolbar>

      <h2 id="organizacion" tabIndex={-1}>
        Cómo se organiza
      </h2>
      <p>
        Cada equipo tiene su carpeta en{' '}
        <PathText>{'equipos\\<identificador>'}</PathText>, con sus versiones en{' '}
        <PathText>{'inventarios\\v0001_….json'}</PathText> y los logos de sus
        programas en <PathText>iconos</PathText>. Lo que se elimina desde Honey
        Check va a <PathText>papelera</PathText> y puede recuperarse.
      </p>

      <h2 id="lectura" tabIndex={-1}>
        Cómo leer los datos
      </h2>
      <SpecList rows={READING_GUIDE} />

      <h2 id="tratamiento" tabIndex={-1}>
        Tratamiento de estos archivos
      </h2>
      <p>
        Los inventarios y los logs contienen seriales, nombres de equipo y rutas
        de programas. Guárdelos y compártalos como información institucional.
        Honey Check no los envía a ningún lugar.
      </p>
    </>
  )
}
