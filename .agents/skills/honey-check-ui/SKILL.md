---
name: honey-check-ui
description: Sistema de diseño de la interfaz de Honey Check (ui) y cómo revisarla con capturas reales. Úsala siempre que vayas a crear o cambiar cualquier pantalla, componente, estilo, texto visible o flujo de Honey Check — una herramienta de soporte nueva, un resultado, una tabla, un gráfico, el panel o el inventario —, aunque el pedido parezca solo de backend pero devuelva algo que la interfaz muestra (resúmenes, verificaciones, tablas, gráficos, acciones por fila).
---

# Interfaz de Honey Check

Honey Check es la herramienta de banco de un técnico de soporte: abre en el equipo de un cliente,
diagnostica y arregla. La interfaz tiene que leerse como un instrumento de medición, no como un
panel SaaS: datos precisos, estados inequívocos, una acción clara a la vez. El técnico ya rechazó
lo genérico (tarjetas con borde grueso, un mapa de bloques que se trababa, códigos de Windows
sueltos, un «plan» y luego un diálogo «Sí, ejecutar»). Cada regla de abajo viene de una de esas
correcciones.

Antes de diseñar, carga también `frontend-design:frontend-design` (dirección visual) y, si hay
cifras o gráficos, `dataviz`. Esta skill fija lo que es propio de Honey Check; esas dos dan el
criterio general.

## Identidad

- **Materiales:** miel (`--honey`), propóleo (marrón muy oscuro, `--propolis`) y cera (`--wax`).
  El riel lateral es de miel; el contenido, sobre la superficie oscura o clara del tema.
- **La celda de panal** es el único ornamento y siempre informa: el catálogo de Soporte en filas
  de panal y `StatusGlyph` (hexágono con su marca) para el estado de cada elemento. No se usa como
  decoración suelta.
- **Tipografía**, solo fuentes del sistema (la app no tiene red):
  - Títulos: `--display` (Bahnschrift).
  - Cifras de lectura: `--readout` con `font-stretch: var(--readout-stretch)` (Bahnschrift
    semicondensada), como la placa de un instrumento. Toda cifra que se compara va así y alineada
    a la derecha.
  - Texto: `--text` (Segoe UI Variable).
  - Rutas, claves y comandos: `--paths` (Consolas), partibles en cualquier punto.
- **Color con significado:** verde `--leaf` (bien), miel `--honey` (aviso o en curso), óxido
  `--oxide` (falló). Lo neutro no se pinta. Un valor solo se colorea si es aviso o falla.
- **Texto en tono de aviso:** `--warn-ink`, nunca `--honey`. La miel sobre blanco tiene 1,8:1 de
  contraste; `--warn-ink` cumple 4,5:1 en los dos temas. La miel sirve para relleno (barras,
  glifos, botón principal) y para texto solo sobre propóleo.
- **Simular lo que el equipo no tiene** (dominio, impresora de red, USB): `tests/simulated_windows.py`
  responde a los mismos comandos y cambia de estado cuando un arreglo funciona; úsalo en las
  pruebas de escenario y en las de Edge para ver la pantalla con fallas de verdad.

Los tokens viven en `ui/src/presentation/styles/tokens.css` y son los únicos dueños de colores,
fuentes y medidas. Un color nuevo se agrega ahí, con su versión oscura, nunca en un módulo.

## Estructura de una pantalla

- **Sin cajas para agrupar.** Las filas se separan con `--hairline` (una línea apenas visible). Un
  contenedor con borde y fondo solo se justifica si es un objeto que se mueve o se superpone
  (diálogo, menú). Nada de tarjetas con borde superior o lateral de color.
- **Una sola tabla:** `DataTable`, con su propio desplazamiento (no se escribe otra `<table>`).
  Para comparaciones, `rowState`; para tablas de dos columnas, `hideHeader` y `rowHeaders`.
- **Jerarquía por tipografía y espacio**, no por marcos: el veredicto en 1,2 rem seminegrita, las
  cifras en lectura, el detalle en `--muted`.
- **Una acción a la vez.** Si un elemento tiene acciones, aparecen al elegirlo (debajo de su fila),
  no como una columna de botones repetida en cada fila.
- **Rutas largas:** se muestran relativas a lo analizado; la ruta completa una sola vez arriba.
- **Teléfono:** a 390 px de ancho no hay desplazamiento horizontal; las tablas pasan a líneas.
- **Valores copiables.** Todo serial, IP, MAC, ruta o cifra va en `Copyable`: un clic lo copia y seleccionar sigue funcionando. Una celda de tabla es de una línea con «…».
- **Ejecutar en el lugar.** Una acción de Soporte desde cualquier vista va en `ActionButton`:
  lo inmediato (`instant=True` en la herramienta) corre con el clic y un aviso; un cambio abre
  su revisión en el panel lateral (`ActionLayer`); solo una consulta con resultado propio lleva
  a su pantalla. Nunca un `LinkButton` a `#soporte?tool=…` para ejecutar algo.
- **Rutas con «Elegir…».** Un parámetro que es una carpeta o un archivo se declara con
  `browse="folder"` (o `"file"` y su filtro): el formulario abre el diálogo de Windows.
  Nunca pedir que el técnico escriba un nombre exacto que no puede saber.
- **Volver no repite.** Una consulta muestra su última versión (`VersionBar`) y lo que cambió (`Changes`); solo «Actualizar» la vuelve a correr.

## Flujo de una herramienta de soporte

Una sola pantalla (`ToolRunner`):

1. **Datos** (`ToolForm`). Lo que llegó por el enlace no se vuelve a pedir.
2. **Revisión previa** (`ConfirmPanel`): una frase con lo que va a pasar (`Plan.summary`), cada
   elemento con su estado (`Plan.checks`) y **un** botón con el nombre de la acción. Ese botón es
   la confirmación: no hay segundo diálogo. Cambiar una opción vuelve a revisar sola. Los pasos
   con su comando quedan plegados en «Ver los pasos y comandos».
3. **En curso** (`RunView`): qué está haciendo ahora, barra fina de miel, Cancelar.
4. **Resultado**: `Verdict` (una frase: cuánto se logró y qué falta), `Readout` (cifras),
   `CheckList` (cada elemento: qué pasó y qué hacer; el código de Windows plegado en «Detalles
   técnicos»), `SpaceExplorer` o `ShareBars` (reparto), `ResultTable`, archivos generados.

Del lado del servidor eso significa: `review` en la `SupportTool` (resumen, verificaciones, si
necesita administrador), `Check.technical` para el código y acciones con `link(...)` en lugar de
texto que diga «use la herramienta X».

## Componentes disponibles

Lee `references/components.md` antes de crear uno nuevo: casi siempre existe uno que sirve.

## Textos

- Español neutro de usted («Revise», «Use»), en voz activa, frases cortas, sin mayúsculas de
  etiqueta.
- Un botón dice exactamente lo que hace y el resultado repite el verbo («Eliminar restos» →
  «Eliminados»).
- Un error nunca es un número: qué pasó + qué hacer. El código va a «Detalles técnicos».
- Nada de «A · B · C», «→» al final de botones ni flechas decorativas.

## Antipatrones que el técnico ya rechazó

| No | En su lugar |
| --- | --- |
| Tarjeta con borde y borde superior de color para cada dato | `Readout`: etiqueta pequeña y cifra |
| Mapa de bloques en canvas (ECharts) | `SpaceExplorer` con barras SVG, teclado y migas reales |
| «Plan» + «Ejecutar el plan» + diálogo «Sí, ejecutar» | `ConfirmPanel` con un botón |
| «No se pudo (código 120)» | «Windows negó el acceso: hace falta administrador» + detalles plegados |
| Tabla con marco, filas alternadas y ruta completa repetida | Tabla con líneas finas y carpeta relativa |
| Borde lateral grueso de color en métricas y avisos | Línea fina arriba y un punto de color solo si hay que mirar |
| Tabla que obliga a agrandar la ventana para ver su barra | `DataTable`: alto máximo y barras siempre a la vista |
| Botones que se parten en dos líneas | Etiquetas cortas («Mostrar», «Abrir») y `white-space: nowrap` |
| Mostrar un identificador interno (`d6621371a0ab9028`) | El nombre del programa en el resumen |
| Texto de una celda partido en varias líneas | Una línea con «…», entero al pasar o al copiar |
| Volver a una herramienta y tener que repetir el análisis | Última versión, «Actualizar» y «Cambios desde…» |
| «Analizar» o «Abrir» en una carpeta del sistema que no lleva a nada | Decir qué es y su acción propia (vaciar la Papelera) |
| Envolver un comando suelto (`gpupdate`, `sfc`) como herramienta | Un solucionador: diagnóstico, arreglo de la causa, verificación |
| «Abrir en el Explorador» que lleva a otra página con «Consultar» | `instant=True`: corre con el clic y un aviso |
| Un cambio que saca al técnico del análisis para revisarlo | El panel lateral sobre la misma pantalla |

Reglas que el lint ya hace cumplir: sin atributo `style` (usa SVG con `width` o clases), Redux solo
por hooks, GSAP solo en `*.gsap.ts`, CSS Modules.

## Revisar con capturas (obligatorio antes de dar algo por terminado)

Mirar la pantalla real encuentra lo que el código no muestra (columnas desalineadas, textos
partidos, huecos). Con Edge y Playwright, sin tocar el Honey Check que el técnico tenga abierto:

```powershell
# 1. Compilar la interfaz
cd ui; npm run build; cd ..
# 2. Instancia de prueba (otro nombre de instancia única; datos en una carpeta temporal)
uv run --frozen python ../../.agents/skills/honey-check-ui/scripts/dev_instance.py --output-dir $env:TEMP\hc-dev
# 3. En otra consola: captura de una ruta (oscuro, 1280 px), con acciones opcionales
uv run --frozen python ../../.agents/skills/honey-check-ui/scripts/shot.py "#soporte?tool=disk.analyze&path=C%3A%5C&auto=1" $env:TEMP\hc-dev\disco.png
```

`shot.py` acepta `--width 390` (teléfono), `--light` y `--do "page.get_by_role(...).click()"`.
Reinicia la instancia después de cada `npm run build` o cambio de Python. Revisa al menos: tema
oscuro y claro, 390 px, un resultado con fallas y uno vacío. Los datos y capturas reales quedan en
la carpeta temporal, nunca en el repositorio; para pantallas que muestran datos, prefiere carpetas
y programas ficticios creados para la prueba.

Al terminar, `npm run check` (formato, lint, tipos y compilación) y `uv run pytest tests/e2e`.
