# Priority fixes

Documento vivo de propuestas pendientes. Mantener exclusivamente en la rama `proposal`; no fusionar este documento en `main`. Cada punto debe incluir criterios de aceptación y estado.

## PF-001 — Soporte nativo para paquetes de instalación ZIP

**Estado:** pendiente. **Prioridad:** alta.

### Contexto

El motor de procesos de instalación admite MSI y ejecutables locales, pero no tiene soporte nativo para paquetes ZIP. Adobe Acrobat Reader es un caso de uso de distribución de paquetes oficiales; se requiere confirmar la procedencia del instalador y resolver cualquier bloqueo de seguridad institucional con el administrador responsable antes de automatizar su instalación.

### Alcance

- Incorporar soporte de paquetes ZIP autorizados al modelo de procedimientos y a su interfaz, conservando compatibilidad con procesos existentes.
- Permitir seleccionar el instalador y sus recursos auxiliares dentro del paquete; conservar rutas relativas y argumentos específicos del fabricante.
- Validar integridad, firma y procedencia, impedir extracción fuera del directorio autorizado, limitar tamaño expandido y comprobar espacio disponible.
- Respetar los controles de seguridad del sistema; si se detecta cuarentena, eliminación o bloqueo, detener el proceso, informar el motivo y requerir resolución autorizada. No desactivar controles ni reintentar para sortearlos.
- Registrar resultados, códigos de salida y verificación de instalación. Gestionar archivos temporales de forma segura y conservar el paquete original.
- Mantener persistencia y reanudación sin duplicar instalaciones completadas.

### Criterios de aceptación

- [ ] Un paquete ZIP legítimo y autorizado puede utilizarse en un procedimiento de instalación.
- [ ] Los paquetes dañados, rutas maliciosas, firmas no confiables y bloqueos de seguridad se gestionan con errores claros.
- [ ] Los procesos MSI/EXE existentes mantienen su comportamiento.
- [ ] Pruebas unitarias, integración y documentación de configuración y operación.

## Propuestas relacionadas

- [Windows Update](PROPOSAL-WINDOWS-UPDATE.md)
