# Validación de Atril 1.1.1

26 de octubre de 2026. Revisión local de prueba; no publicada como release.

## Incidencia y corrección

Las capturas aportadas desde Linux Mint 22.1 muestran `ValueError` en una función `lambda`: el filtro vacío recibido por el diálogo de guardado no está en la lista de formatos. El usuario confirma que puede grabar, cambiar de dispositivo y guardar después de cerrar el aviso.

Se ha reproducido la excepción al emitir una selección vacía sobre el diálogo de la versión 1.1.0. La revisión conserva la última selección válida, admite eventos vacíos sin excepción y mantiene el selector nativo del escritorio. El nombre propuesto empieza sin extensión. Al guardar se eliminan las extensiones de audio encadenadas y se añade una sola extensión del formato elegido, sin eliminar otros puntos del título. Si el nombre definitivo ya existe, se solicita confirmación antes de sustituirlo.

## Comprobación automatizada

- 52 pruebas superadas con Python 3.12, Qt 5.15.13 y PyQt 5.15.10.
- 44 pruebas existentes y 8 pruebas de regresión del guardado.
- Eventos de filtro vacío/desconocido, selección final vacía, nombre propuesto sin extensión y disponibilidad de WAV cuando falta FFmpeg.
- Los tres formatos con nombres sin extensión, con extensión anterior, con extensiones duplicadas y con mayúsculas.
- Conservación de puntos del título y cancelación de la sustitución de un archivo existente tras normalizar el nombre.
- Exportación real desde el flujo de guardado a WAV, FLAC y MP3; códecs comprobados con ffprobe.
- Las pruebas anteriores conservan la comprobación de FLAC sin pérdida y WAV idéntico al original.

Las pruebas del diálogo se ejecutan con Qt offscreen y eventos controlados. Queda pendiente confirmar visualmente el diálogo nativo de Linux Mint con el nuevo paquete instalado. No se ha grabado un micrófono físico durante esta revisión ni modificado la instalación existente del equipo.

El DEB se ha reconstruido para 1.1.1. La receta RPM también refleja 1.1.1, pero no se ha construido un RPM en esta revisión. La receta Arch sigue correspondiendo a la versión estable 1.0.0.
