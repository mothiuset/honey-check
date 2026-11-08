// Registro de módulos: cada herramienta declara su grupo, su ruta y sus apartados. El menú y las
// rutas se generan desde aquí, de modo que un módulo nuevo no toca el núcleo de la interfaz.

import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

export interface ModuleSection {
  readonly anchor: string
  readonly label: string
}

export interface ModuleDefinition {
  readonly id: string
  readonly group: ModuleGroup
  readonly label: string
  readonly page: LazyExoticComponent<ComponentType>
  readonly sections?: readonly ModuleSection[]
}

export const GROUPS = [
  'Análisis del equipo',
  'Soporte',
  'Equipos guardados',
  'Datos',
] as const
export type ModuleGroup = (typeof GROUPS)[number]

const page = <K extends string>(
  load: () => Promise<Record<K, ComponentType>>,
  name: K,
) => lazy(async () => ({ default: (await load())[name] }))

export const MODULES: readonly ModuleDefinition[] = [
  {
    id: 'panel',
    group: 'Análisis del equipo',
    label: 'Panel',
    page: page(
      () => import('@/presentation/analysis/pages/PanelPage'),
      'PanelPage',
    ),
  },
  {
    id: 'hardware',
    group: 'Análisis del equipo',
    label: 'Hardware',
    page: page(
      () => import('@/presentation/analysis/pages/HardwarePage'),
      'HardwarePage',
    ),
    sections: [
      { anchor: '', label: 'Todo el hardware' },
      { anchor: 'identificacion', label: 'Identificación' },
      { anchor: 'procesador', label: 'Procesador' },
      { anchor: 'memoria', label: 'Memoria' },
      { anchor: 'graficos', label: 'Tarjetas gráficas' },
      { anchor: 'pantallas', label: 'Pantallas' },
      { anchor: 'red', label: 'Adaptadores de red' },
      { anchor: 'bateria', label: 'Batería' },
      { anchor: 'tpm', label: 'TPM' },
      { anchor: 'dispositivos', label: 'Dispositivos con errores' },
    ],
  },
  {
    id: 'almacenamiento',
    group: 'Análisis del equipo',
    label: 'Almacenamiento',
    page: page(
      () => import('@/presentation/analysis/pages/StoragePage'),
      'StoragePage',
    ),
  },
  {
    id: 'software',
    group: 'Análisis del equipo',
    label: 'Software',
    page: page(
      () => import('@/presentation/analysis/pages/SoftwarePage'),
      'SoftwarePage',
    ),
    sections: [
      { anchor: '', label: 'Programas' },
      { anchor: 'fuentes', label: 'Fuentes consultadas' },
      { anchor: 'limites', label: 'Qué no puede detectarse' },
    ],
  },
  {
    id: 'perifericos',
    group: 'Análisis del equipo',
    label: 'Periféricos e impresoras',
    page: page(
      () => import('@/presentation/analysis/pages/PeripheralsPage'),
      'PeripheralsPage',
    ),
    sections: [
      { anchor: '', label: 'Todo' },
      { anchor: 'impresoras', label: 'Impresoras' },
      { anchor: 'dispositivos', label: 'Dispositivos conectados' },
    ],
  },
  {
    id: 'sistema',
    group: 'Análisis del equipo',
    label: 'Sistema',
    page: page(
      () => import('@/presentation/analysis/pages/SystemPage'),
      'SystemPage',
    ),
    sections: [
      { anchor: '', label: 'Sistema operativo' },
      { anchor: 'actualizaciones', label: 'Actualizaciones instaladas' },
      { anchor: 'duracion', label: 'Duración del análisis' },
    ],
  },
  {
    id: 'seguridad',
    group: 'Análisis del equipo',
    label: 'Seguridad',
    page: page(
      () => import('@/presentation/analysis/pages/SecurityPage'),
      'SecurityPage',
    ),
    sections: [
      { anchor: '', label: 'Estado general' },
      { anchor: 'antivirus', label: 'Antivirus' },
      { anchor: 'firewall', label: 'Firewall' },
      { anchor: 'cifrado', label: 'Cifrado de volúmenes' },
    ],
  },
  {
    id: 'soporte',
    group: 'Soporte',
    label: 'Herramientas',
    page: page(
      () => import('@/presentation/support/pages/SupportPage'),
      'SupportPage',
    ),
    sections: [
      { anchor: '', label: 'Todas' },
      { anchor: 'espacio-en-disco', label: 'Espacio en disco' },
      { anchor: 'limpieza', label: 'Limpieza' },
      { anchor: 'programas', label: 'Programas' },
      { anchor: 'impresoras', label: 'Impresoras' },
      { anchor: 'red', label: 'Red' },
      { anchor: 'dominio-y-directivas', label: 'Dominio y directivas' },
      { anchor: 'certificados', label: 'Certificados' },
      { anchor: 'servicios-y-procesos', label: 'Servicios y procesos' },
      { anchor: 'sistema', label: 'Sistema' },
      { anchor: 'registro', label: 'Registro' },
      { anchor: 'credenciales', label: 'Credenciales' },
    ],
  },
  {
    id: 'procesos',
    group: 'Soporte',
    label: 'Procesos de instalación',
    page: page(
      () => import('@/presentation/support/pages/ProceduresPage'),
      'ProceduresPage',
    ),
  },
  {
    id: 'historial',
    group: 'Soporte',
    label: 'Historial',
    page: page(
      () => import('@/presentation/support/pages/HistoryPage'),
      'HistoryPage',
    ),
  },
  {
    id: 'equipos',
    group: 'Equipos guardados',
    label: 'Equipos y versiones',
    page: page(
      () => import('@/presentation/devices/pages/DevicesPage'),
      'DevicesPage',
    ),
  },
  {
    id: 'comparar',
    group: 'Equipos guardados',
    label: 'Comparar',
    page: page(
      () => import('@/presentation/devices/pages/ComparePage'),
      'ComparePage',
    ),
  },
  {
    id: 'exportaciones',
    group: 'Datos',
    label: 'Carpeta de datos',
    page: page(
      () => import('@/presentation/data/pages/DataFolderPage'),
      'DataFolderPage',
    ),
  },
]

export function moduleById(id: string): ModuleDefinition | undefined {
  return MODULES.find((module) => module.id === id)
}
