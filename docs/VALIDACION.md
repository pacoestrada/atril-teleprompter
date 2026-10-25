# Validación de Atril 1.0.0

Fecha: 25 de octubre de 2026.

- 23 pruebas automatizadas superadas con Python 3 y PyQt5 5.15.10 / Qt 5.15.13.
- Importación UTF-8, UTF-16 y Windows-1252; texto español; DOCX y ODT básicos.
- Límites de archivo, prevención de expansión ZIP excesiva, rechazo de entidades XML.
- Guardado atómico y recuperación de sesión y del guion anterior.
- Reproducción, pausa, cuenta atrás, final y repetición; avance manual y atajos.
- Escritura en el editor sin activación de los atajos de lectura.
- Presentación a 1280×860, 1024×700, 800×600 y 1366×708 píxeles lógicos.
- Renderizado de Qt a escala 2, con ventana de 1280×860 y captura de 2560×1720.
- Paquete Debian generado sin privilegios y metadatos inspeccionados.

Las pruebas de interfaz se hicieron con la plataforma offscreen de Qt. No equivalen a una instalación y sesión de uso en el Linux Mint de Paco, ni verifican todos los compositores, pedales o configuraciones multimonitor. La prueba de lectura real y de instalación en ese equipo sigue pendiente.
