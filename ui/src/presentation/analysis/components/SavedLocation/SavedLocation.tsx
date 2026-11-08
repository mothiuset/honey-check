import { Button, Notice, PathText } from '@/presentation/shared/components'
import { useOpenFolder } from '@/presentation/shared/hooks/useOpenFolder'

export interface SavedLocationProps {
  readonly prefix: string
  readonly directory: string
  readonly fileName: string
}

/** Ruta completa del archivo del análisis y el botón para abrir su carpeta. */
export function SavedLocation({
  prefix,
  directory,
  fileName,
}: SavedLocationProps) {
  const openFolder = useOpenFolder()
  return (
    <Notice>
      <p>
        {prefix} <PathText>{`${directory}\\${fileName}`}</PathText>
      </p>
      <Button
        size="small"
        onClick={() => {
          openFolder(directory)
        }}
      >
        Abrir carpeta
      </Button>
    </Notice>
  )
}
