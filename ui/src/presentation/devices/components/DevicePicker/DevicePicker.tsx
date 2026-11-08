import { Button, Field, Lede } from '@/presentation/shared/components'
import { useDevicePicker } from '../../hooks/useDevicePicker'
import type { DevicePickerProps } from './DevicePicker.types'
import styles from './DevicePicker.module.css'

export function DevicePicker({ title, value, onChange }: DevicePickerProps) {
  const picker = useDevicePicker(value, onChange)
  return (
    <section className={styles.picker} aria-label={title}>
      <h3 className={styles.title}>{title}</h3>
      {value ? (
        <div className={styles.chosen}>
          <strong>{value.device.hostname ?? 'Equipo sin nombre'}</strong>
          <span className={styles.sub}>
            {[value.device.manufacturer, value.device.model]
              .filter(Boolean)
              .join(' ')}
          </span>
          <Field label="Versión">
            <select
              value={value.inventoryId}
              onChange={(event) => {
                picker.pickVersion(event.target.value)
              }}
            >
              {picker.options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Button size="small" onClick={picker.clear}>
            Cambiar equipo
          </Button>
        </div>
      ) : (
        <>
          <input
            type="search"
            className={styles.search}
            value={picker.text}
            aria-label={`${title}: buscar equipo`}
            placeholder="Buscar por nombre, serial, modelo o sistema"
            onChange={(event) => {
              picker.search(event.target.value)
            }}
          />
          {picker.results.length ? (
            <ul
              className={styles.results}
              aria-label={`Resultados para ${title}`}
            >
              {picker.results.map((device) => (
                <li key={device.deviceKey}>
                  <button
                    type="button"
                    className={styles.option}
                    data-part="picker-option"
                    onClick={() => {
                      picker.choose(device)
                    }}
                  >
                    <strong>{device.hostname ?? 'Equipo sin nombre'}</strong>
                    <span className={styles.sub}>
                      {[device.manufacturer, device.model, device.serialNumber]
                        .filter(Boolean)
                        .join(' ')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : picker.text.trim() ? (
            <Lede>No hay coincidencias todavía.</Lede>
          ) : null}
        </>
      )}
    </section>
  )
}
