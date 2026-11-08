import type { AnchorHTMLAttributes, MouseEvent } from 'react'
import { navigate } from '../hashRoute'

export interface RouteLinkProps extends Omit<
  AnchorHTMLAttributes<HTMLAnchorElement>,
  'href'
> {
  readonly href: string
}

/** Enlace interno: repetir el enlace actual vuelve a llevar al apartado. */
export function RouteLink({ href, onClick, ...rest }: RouteLinkProps) {
  function handle(event: MouseEvent<HTMLAnchorElement>): void {
    onClick?.(event)
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey
    )
      return
    event.preventDefault()
    navigate(href)
  }
  return <a href={href} onClick={handle} {...rest} />
}
