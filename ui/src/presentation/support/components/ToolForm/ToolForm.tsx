import type { FormEvent } from 'react'
import type { ParamValue, ToolDefinition, ToolParam } from '@/application'
import { Button, Check, Field, Toolbar } from '@/presentation/shared/components'
import { browseOf, type PathBrowse } from '../../formatters/browse'
import { usePathPicker } from '../../hooks/usePathPicker'
import { SourcePicker } from '../SourcePicker/SourcePicker'
import styles from './ToolForm.module.css'

interface ToolFormProps {
  readonly tool: ToolDefinition
  readonly values: Readonly<Record<string, ParamValue>>
  readonly missing: readonly string[]
  readonly busy: boolean
  readonly onChange: (name: string, value: ParamValue) => void
  readonly onSubmit: () => void
  /** Datos que trajo el enlace (el programa elegido, por ejemplo): no se vuelven a pedir. */
  readonly fixed: ReadonlySet<string>
  /** Sin botón cuando la revisión ya está a la vista y se actualiza sola. */
  readonly showSubmit: boolean
}

const asText = (value: ParamValue | undefined): string =>
  value === null || value === undefined
    ? ''
    : Array.isArray(value)
      ? value.join('\n')
      : String(value)

function ParamInput({
  param,
  value,
  onChange,
}: {
  param: ToolParam
  value: ParamValue | undefined
  onChange: (value: ParamValue) => void
}) {
  if (param.kind === 'bool')
    return (
      <Check label={param.label} checked={value === true} onChange={onChange} />
    )
  const source = param.source
  if (param.kind === 'choice' && source)
    return (
      <SourcePicker
        param={{ ...param, source }}
        value={value ? [asText(value)] : []}
        onChange={(picked) => {
          onChange(picked[0] ?? '')
        }}
        multiple={false}
      />
    )
  if (param.kind === 'multi' && source)
    return (
      <SourcePicker
        param={{ ...param, source }}
        value={Array.isArray(value) ? (value as readonly string[]) : []}
        onChange={onChange}
      />
    )
  const label = `${param.label}${param.required ? ' *' : ''}`
  let control
  if (param.kind === 'choice')
    control = (
      <select
        name={param.name}
        value={asText(value)}
        onChange={(event) => {
          onChange(event.target.value)
        }}
      >
        {param.choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    )
  else if (param.kind === 'multi')
    control = (
      <textarea
        name={param.name}
        rows={4}
        value={asText(value)}
        onChange={(event) => {
          const lines = event.target.value.split('\n')
          onChange(lines.filter((line) => line.trim() !== ''))
        }}
      />
    )
  else
    control = (
      <input
        name={param.name}
        type={
          param.kind === 'secret'
            ? 'password'
            : param.kind === 'number'
              ? 'number'
              : 'text'
        }
        autoComplete="off"
        spellCheck={false}
        maxLength={param.maxLength}
        value={asText(value)}
        onChange={(event) => {
          onChange(
            param.kind === 'number'
              ? event.target.valueAsNumber
              : event.target.value,
          )
        }}
      />
    )
  const browse = browseOf(param)
  return (
    <Field label={label} grow>
      {browse ? (
        <span className={styles.browse}>
          {control}
          <BrowseButton
            browse={browse}
            title={param.label}
            onPicked={onChange}
          />
        </span>
      ) : (
        control
      )}
      {param.help ? <small className={styles.help}>{param.help}</small> : null}
    </Field>
  )
}

/** «Elegir…»: abre el diálogo de Windows al frente y escribe la ruta elegida. */
function BrowseButton({
  browse,
  title,
  onPicked,
}: {
  browse: PathBrowse
  title: string
  onPicked: (value: string) => void
}) {
  const picker = usePathPicker()
  return (
    <Button
      onClick={() => {
        void picker.pick(browse.kind, title, browse.filter).then((path) => {
          if (path) onPicked(path)
        })
      }}
      disabled={picker.open}
    >
      {picker.open ? 'Eligiendo…' : 'Elegir…'}
    </Button>
  )
}

/** Formulario generado desde la definición de la herramienta: el servicio valida cada valor. */
export function ToolForm({
  tool,
  values,
  missing,
  busy,
  onChange,
  onSubmit,
  fixed,
  showSubmit,
}: ToolFormProps) {
  const shown = tool.params.filter((param) => !fixed.has(param.name))
  function submit(event: FormEvent): void {
    event.preventDefault()
    onSubmit()
  }
  return (
    <form className={styles.form} onSubmit={submit} aria-label={tool.title}>
      {shown.length ? (
        <div className={styles.fields}>
          {shown.map((param) => (
            <ParamInput
              key={param.name}
              param={param}
              value={values[param.name]}
              onChange={(value) => {
                onChange(param.name, value)
              }}
            />
          ))}
        </div>
      ) : null}
      {showSubmit ? (
        <Toolbar align="center">
          <Button
            type="submit"
            tone={tool.risk === 'read' ? 'primary' : 'default'}
            disabled={busy || missing.length > 0}
          >
            {tool.risk === 'read' ? 'Consultar' : 'Revisar antes de hacerlo'}
          </Button>
          {missing.length ? (
            <span className={styles.missing}>Falta: {missing.join(', ')}</span>
          ) : null}
        </Toolbar>
      ) : null}
    </form>
  )
}
