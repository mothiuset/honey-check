import type { ToolResult } from '@/application'
import {
  Button,
  PathText,
  VisuallyHidden,
} from '@/presentation/shared/components'
import { CheckList } from '../CheckList/CheckList'
import { Readout } from '../Readout/Readout'
import { ResultTable } from '../ResultTable/ResultTable'
import { ShareBars } from '../ShareBars/ShareBars'
import { SpaceExplorer } from '../SpaceExplorer/SpaceExplorer'
import styles from './ResultView.module.css'

interface ResultViewProps {
  readonly result: ToolResult
  readonly onOpenFolder: (path: string) => void
}

const parentOf = (path: string) => path.replace(/[\\/][^\\/]*$/, '')

/**
 * El resultado que la herramienta devolvió, sin conocer la herramienta: datos de lectura, cada
 * elemento con su estado, el reparto del espacio, tablas y archivos generados. El veredicto en una
 * frase lo pone quien muestra la ejecución.
 */
export function ResultView({ result, onOpenFolder }: ResultViewProps) {
  return (
    <section className={styles.result} aria-labelledby="result-title">
      <h2 id="result-title">
        <VisuallyHidden>Resultado</VisuallyHidden>
      </h2>
      {result.summary.length ? <Readout facts={result.summary} /> : null}
      {result.checks.length ? <CheckList checks={result.checks} /> : null}

      {result.charts.map((chart) =>
        chart.kind === 'treemap' ? (
          <SpaceExplorer key={chart.id} chart={chart} />
        ) : (
          <ShareBars key={chart.id} chart={chart} />
        ),
      )}
      {result.tables.map((table) => (
        <ResultTable key={table.id} table={table} />
      ))}

      {result.text ? <pre className={styles.text}>{result.text}</pre> : null}

      {result.files.length ? (
        <>
          <h3>Archivos generados</h3>
          <ul className={styles.files}>
            {result.files.map((file) => (
              <li key={file.path}>
                <span className={styles.fileLabel}>{file.label}</span>
                <PathText>{file.path}</PathText>
                <Button
                  size="small"
                  tone="ghost"
                  onClick={() => {
                    onOpenFolder(parentOf(file.path))
                  }}
                >
                  Abrir carpeta
                </Button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  )
}
