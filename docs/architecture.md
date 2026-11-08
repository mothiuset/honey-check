# Arquitectura

Ports & Adapters con dependencias hacia el interior. `composition.py` es el único módulo que une
casos de uso y adaptadores concretos.

```text
presentation ──► application ──► domain
infrastructure ─► application ──► domain
composition ────► infrastructure + application
app.py ─────────► composition + presentation
```

| Capa | Ruta | Responsabilidad |
| --- | --- | --- |
| Domain | `src/honey_check/domain` | Contrato tipado, `Observed`, clasificación, nombres, migraciones, comparación. Sin Windows ni E/S |
| Application | `src/honey_check/application` | Puertos, coordinación del análisis, casos de uso |
| Infrastructure | `src/honey_check/infrastructure` | Módulos de inventario, PowerShell/CIM, Registro, archivos, llamadas nativas, JSON, logs |
| Presentation | `src/honey_check/presentation` | API HTTP local, bandeja y la interfaz compilada en `web/dist` |

## Interfaz (`ui/`)

React 18 con TypeScript estricto, Redux Toolkit y CSS Modules, compilada con Vite a
`presentation/web/dist`. El servidor sirve solo los archivos que encuentra allí al arrancar.

```text
src/domain          contrato del inventario, equipos, comparación y estado (sin frameworks)
src/application     puerto HoneyCheckGateway y casos de uso por capacidad
src/infrastructure  cliente HTTP con CSRF y adaptador del puerto
src/composition     container.ts: el único lugar que elige el adaptador
src/presentation
  store/            slices, thunks y selectores; único lugar que importa Redux
  shared/           componentes, formateadores, hooks, navegación y tipos compartidos
  app/              armazón: menú, barra de estado fija, avisos, diálogo y registro de módulos
  analysis/ devices/ data/   una carpeta por capacidad: pages, components, hooks, formatters
```

Reglas que ESLint hace cumplir (`ui/eslint.config.js`):

- Los componentes llegan al store solo por hooks; ningún `.tsx` importa Redux ni el store.
- Las animaciones usan GSAP y viven en archivos `*.gsap.ts`.
- Sin atributo `style` en el marcado: cada componente tiene su módulo CSS y los tokens viven en
  `presentation/styles/tokens.css`.
- La presentación usa la API pública de `@/application`, nunca el dominio ni la infraestructura.

## Flujo de un análisis

```text
Interfaz o bandeja
  └─ InventoryService.start_scan
       └─ ScanCoordinator (hilo supervisor)
            ├─ hasta 3 módulos a la vez, cada uno en su hilo y con su límite de tiempo
            │    └─ Collector.collect(ctx) ─► puertos de solo lectura
            ├─ ensambla y valida Inventory
            └─ InventoryStore.save ─► JSON atómico junto al ejecutable
                 └─ si falla: queda en memoria y se ofrece otra carpeta
```

## Módulos de inventario

Cada módulo cumple el protocolo `Collector` (`name`, `timeout_s`, `collect`) y devuelve una sección
tipada. Los fallos se quedan en el módulo:

- Una clase WMI que falla se registra y la sección sale con esos valores como desconocidos.
- `ModuleFailed` o cualquier excepción dejan la sección en `null` y el análisis continúa.
- Al superar el límite se cancela su token, lo que mata de verdad el subproceso en curso. Si su
  hilo no termina, se abandona y su resultado se descarta.

Para añadir un módulo: cree el `Collector`, añada su sección a `domain/inventory.py`, regístrelo en
`composition.default_collectors`, regenere el esquema con `tools/write_schema.py` y añada su celda
en `ui/src/presentation/components/HoneyComb.vue`. Una vista nueva se registra en
`ui/src/presentation/registry.ts`: el menú y las rutas salen de ahí.

## Soporte

- `domain/support.py`: contrato de las herramientas (definición, plan, resultado y ejecución).
  `domain/procedures.py`: procesos de instalación y sus plantillas.
- `application/support/`: el motor (`engine.py`) valida parámetros, sella el plan con la revisión
  previa de la herramienta (resumen, verificaciones y si hace falta administrador), exige
  confirmación, ejecuta en un hilo con cancelación y registra. Lo que necesita administrador sin
  sesión elevada pasa por el puerto `ElevatedExecutor`. `procedures.py`
  decide la secuencia de un proceso: qué paso sigue, cuándo espera al técnico y cuándo termina.
  `context.py` ofrece a cada herramienta el registro, los comandos y `first_that_works`.
- `infrastructure/support/tools/`: cada módulo exporta `TOOLS`. Una herramienta es una
  `SupportTool` con su definición, una función que arma el plan y otra que lo ejecuta, y devuelve un
  `ToolResult` (resumen, verificaciones, tablas con acciones por fila, gráficos, archivos) que la
  interfaz muestra sin conocer la herramienta. Añadir una es añadir su módulo en
  `composition.support_tools`. La revisión previa es la función `review` de la `SupportTool`.
- `infrastructure/support/elevated.py`: el proceso de administrador de una sola acción (tubería
  autenticada, JSON). `removal.py`: eliminar insistiendo por vías distintas.
  `infrastructure/windows/locks.py` (qué proceso usa un archivo y cerrarlo), `errors.py` (códigos
  de Windows en palabras del técnico) y `session.py` (usuario de la sesión para el proceso
  elevado).
- `presentation/http/support_routes.py`: `/api/support/tools`, `/plans`, `/runs` y
  `/api/procedures`, detrás de la misma sesión y protección CSRF que el resto.

## Ciclo de vida

`app.py` adquiere la instancia única, arranca el servidor, comprueba su salud, abre el navegador
y deja la bandeja en el hilo principal. **Salir** cancela el análisis, mata los subprocesos,
detiene el servidor y libera el mutex.

## Integraciones futuras

Estas integraciones no existen todavía. Los puntos donde encajarían son reales:

| Futuro | Punto de extensión |
| --- | --- |
| Plataforma web o API de sincronización | Un consumidor del JSON versionado, o un nuevo caso de uso con su puerto |
| PostgreSQL o historial de activos | Otra implementación de `InventoryStore`; el campo `system_uuid` identifica el equipo |
| Comparación de cambios de hardware | `domain/compare.py` ya es independiente de la persistencia |
| Reportes PDF o Excel | Un exportador que reciba `Inventory` |
| Diagnósticos de software | Un `Collector` adicional |
| Asociación de equipos, funcionarios y casos | Fuera de Honey Check: pertenece a la plataforma web |

Honey Check no conoce RavenX3 ni ninguna infraestructura remota.
