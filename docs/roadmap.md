# Trabajo pendiente

El orden acordado con el técnico. Quien termine o cambie un punto actualiza este archivo en el
mismo commit. Las decisiones que se toman al hacerlo van a [decisiones](decisions.md).

## En orden

1. **Procesos de instalación, fáciles**: elegir la carpeta de instaladores y que detecte cada
   programa (`.exe`, `.msi`) con sus argumentos silenciosos sugeridos; la configuración se arma
   sola, se guarda, se copia o se edita con formulario (el JSON solo a pedido). Firma digital
   (token) y ofimática como módulos extra claramente opcionales. Decir con claridad qué hace
   «ejecutar» y qué pasa en cada paso.
2. **Ayuda**: una sección de documentación dentro de la app y, en cada herramienta, una
   explicación breve al pasar el puntero con un enlace a su ayuda.
3. **Deshacer o revertir** desde el aviso de una acción ya hecha (predeterminada anterior, lo que
   se envió a la Papelera).
4. **Archivos por tipo.** En el reparto por extensión, elegir una lista sus archivos, con
   selección para enviarlos a la Papelera.
5. **Respaldos con «Restaurar».** Una vista de respaldos donde cada uno se restaura, no solo se
   muestra dónde quedó: `.reg` (`reg import`), `.acl` (`icacls /restore`), tareas (`schtasks
   /create`), reglas de firewall, `Registry.pol` y dispositivos quitados.
6. **Solucionadores «Inicio lento» y «Disco lleno»**, con el mismo patrón que los demás.
7. **Energía:** perfil de alto rendimiento calculado según el hardware y volver al
   predeterminado. Sin modo de bajo consumo.
8. **Rediseño del resto** (panel, inventario, catálogo) con el lenguaje de Soporte.

## Validaciones reales pendientes

Las que solo están simuladas (dominio, impresora física, red caída, Windows dañado, UAC con un
programa en uso) se listan en [pruebas](testing.md#validaciones-pendientes).

## Hecho recientemente

- Impresora de red con solo la IP: modelo por SNMP y controlador elegido solo (instalado,
  almacén, carpeta, universal de la marca o genérico); agregar, quitar y cambiar controladores.

- Controladores: qué falta, instalados con sus aparatos, instalar desde una carpeta lo que
  sirve, reparar, quitar con respaldo y respaldar todos. «Elegir…» con el diálogo de Windows
  para cualquier ruta.

- Almacenamiento con letras, discos externos, fabricante o controladora y acciones por
  unidad; una sola tabla con desplazamiento propio; métricas y avisos sin borde lateral.

- Periféricos: un aparato por fila con lo que hace; no conectados separados en emparejados
  y restos; quitar restos con respaldo, restaurar y olvidar un Bluetooth.
- Resultados que avisan si el equipo cambió (huella de la consulta) y programas por tamaño
  leídos en vivo.
- Ejecutar donde está el técnico: lo inmediato con el clic y un aviso, los cambios en un panel
  lateral, y el Explorador al frente.
- Valores copiables con un clic, tablas en una línea, carpetas del sistema con su acción.
- Versiones de cada consulta: volver sin repetir, «Actualizar», «Cambios desde…».
- `compilar.cmd` y número de compilación visible en la app y en la descarga.
