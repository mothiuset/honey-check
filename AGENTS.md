# Honey Check

Aplicación portable de inventario y soporte para equipos Windows. Antes de cambiarla, lea
`docs/architecture.md`, `docs/security.md` y `docs/decisions.md`.

- Dependencias hacia el interior; solo `composition.py` conoce los adaptadores concretos.
- El inventario solo lee. Los cambios viven en `infrastructure/support/` y pasan por el motor de
  soporte: plan con comandos equivalentes, confirmación, respaldo y verificación.
- Nunca: usar `Win32_Product`, ejecutar lo leído del Registro sin el plan del técnico, escribir
  claves de directivas (GPO) o el contenido de `Registry.pol` (solo `tools/policies.py` lo respalda
  y renombra si su cabecera es inválida o Windows registró el evento 1096), tocar el antivirus, AppLocker o WDAC, borrar registros del sistema,
  abrir el servidor a la red, ni añadir telemetría o llamadas salientes.
- Cada vía de una acción tiene alternativa (`first_that_works`) y la acción se verifica después.
- Dependencias de ejecución: licencia permisiva y sin telemetría (`tools/licenses.py`).
- Inventarios, logs y capturas reales nunca entran al repositorio; los fixtures son ficticios.
- `docs/testing.md` separa mocks de pruebas reales: marque una validación solo con evidencia.
- Interfaz: siga `.agents/skills/honey-check-ui` (sistema de diseño, componentes y revisión con
  capturas en Edge) para cualquier pantalla o resultado que la interfaz muestre.

- Soporte: solucionadores (diagnóstico, arreglo de solo la causa, verificación), no comandos sueltos.
- Decisiones vigentes en `docs/decisions.md` (las reemplazadas lo dicen: no se vuelve a ellas); qué sigue y en qué orden, en `docs/roadmap.md`. Ambos se actualizan en el mismo commit que el código.
- Compilar en este equipo: `compilar.cmd`. Publicar: `tools/publish.py`. Sin GitHub Actions (son pagas en este repositorio).

Comprobaciones en el `README.md`; ejecutable en `docs/build.md`.
