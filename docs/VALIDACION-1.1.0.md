# Validación de Atril 1.1.0 · Grabación de voz

25 de octubre de 2026. Candidato local, todavía no publicado como release.

## Comprobado

- 44 pruebas automatizadas en Python 3 y PyQt5 5.15.11.
- Conservación de las 23 pruebas originales de documentos, lectura, teclado, recuperación y disposición.
- PCM de 16 bits: ganancia positiva/negativa, detección de saturación de origen y salida, RMS y pico.
- Grabación por bloques, pausa sin insertar silencios, reanudación y cierre de fragmentos parciales.
- Envolvente limitada a cinco segundos; la toma completa se escribe en disco.
- WAV recuperable antes de cerrar la toma, permisos privados y gestión del límite RIFF.
- Selección de dispositivo y negociación de formato con una entrada controlada de prueba; no se ha usado un micrófono físico.
- WAV exportado idéntico al original; FLAC decodificado idéntico al PCM; MP3 decodificable con canales y duración comprobados mediante FFmpeg/ffprobe.
- Exportación en segundo plano, cancelación sin reemplazar destino, error de codificador, error de escritura y cierre después de guardar.
- Atajos de audio, lectura independiente, teclado del control de ganancia sin interferir con el guion.
- Revisión visual con Qt offscreen a 1280×860 y 740×650; disposición comprobada también a 1024×700 y pantalla completa.
- Paquete DEB construido y extraído; módulos de audio y dependencias declaradas comprobados. Las 44 pruebas también se han ejecutado sobre los archivos extraídos del paquete.

## Pendiente de uso real

- Instalar el DEB en Linux Mint y probar el micrófono y las interfaces de audio del equipo.
- Comprobar la lista y el cambio de dispositivos, reconexión USB y permisos reales de PulseAudio/PipeWire.
- Verificar el selector de archivos nativo del escritorio al guardar en las tres extensiones.
- Comprobar una grabación larga con lectura simultánea y, si procede, pantalla 4K al 200 %.
- El RPM tiene la receta actualizada, pero no se ha construido ni probado en esta sesión. La receta Arch distribuida sigue correspondiendo a la versión estable 1.0.0.

El entorno de desarrollo no tiene acceso al sistema de sonido del PC. Las pruebas de captura usan PCM de prueba y un dispositivo controlado; no certifican el funcionamiento de un micrófono real. La exportación sí usa FFmpeg y archivos de audio reales.
