import type { AnchorHTMLAttributes, ButtonHTMLAttributes } from 'react'
import styles from './Button.module.css'

export type ButtonTone = 'default' | 'primary' | 'danger' | 'ghost'
export type ButtonSize = 'normal' | 'small'

interface Look {
  readonly tone?: ButtonTone | undefined
  readonly size?: ButtonSize | undefined
}

function classOf(
  { tone = 'default', size = 'normal' }: Look,
  extra?: string,
): string {
  return [styles.button, styles[tone], styles[size], extra]
    .filter(Boolean)
    .join(' ')
}

export type ButtonProps = Look & ButtonHTMLAttributes<HTMLButtonElement>

export function Button({
  tone,
  size,
  className,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={classOf({ tone, size }, className)}
      {...rest}
    />
  )
}

export type LinkButtonProps = Look & AnchorHTMLAttributes<HTMLAnchorElement>

/** Un enlace (descarga, ruta) con el aspecto de un botón. */
export function LinkButton({
  tone,
  size,
  className,
  ...rest
}: LinkButtonProps) {
  return <a className={classOf({ tone, size }, className)} {...rest} />
}
