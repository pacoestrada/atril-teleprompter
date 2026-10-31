# Atril Teleprónter para Arch Linux

Paquete nativo `atril-teleprompter-2.1.0-1-any.pkg.tar.zst`, construido con
`makepkg` a partir de las fuentes de la versión 2.1.0. No convierte el DEB ni
el RPM. El nombre `atril-teleprompter` evita conflictos con el visor Atril.

## Instalar el paquete descargado

Desde la carpeta de descarga, con Arch actualizado:

```bash
sudo pacman -Syu
sudo pacman -U ./atril-teleprompter-2.1.0-1-any.pkg.tar.zst
```

Pacman resuelve las dependencias `python`, `python-pyqt5`, `qt5-multimedia` y `ffmpeg` desde los
repositorios de Arch. Después busca **Atril Teleprónter** en el menú de
aplicaciones o ejecuta `atril-teleprompter`. La aplicación funciona sin
conexión una vez instalada. La fuente opcional `ttf-dejavu` permite utilizar
la tipografía prevista en el diseño.

Si descargas también `SHA256SUMS.txt`, comprueba el paquete con:

```bash
sha256sum --ignore-missing -c SHA256SUMS.txt
```

Comprueba que aparezca `OK` para el archivo `.pkg.tar.zst`. Estas sumas
detectan descargas dañadas; no son una firma criptográfica del autor.

## Construir desde las fuentes

Instala las herramientas y clona uno de los repositorios:

```bash
sudo pacman -Syu --needed base-devel git
git clone https://github.com/pacoestrada/atril-teleprompter.git
# Alternativa: git clone https://gitlab.com/PacoEstrada/atril-teleprompter.git
cd atril-teleprompter/packaging/arch
less PKGBUILD
makepkg -si
```

Ejecuta `makepkg` con tu usuario habitual, sin `sudo`. La receta descarga
la versión estable etiquetada, comprueba su SHA-256, ejecuta las pruebas y
genera el paquete. `-s` instala dependencias y `-i` instala el resultado.
Para construir sin instalar la aplicación, utiliza `makepkg -s`.

Para regenerar los metadatos después de modificar la receta:

```bash
makepkg --printsrcinfo > .SRCINFO
```

## Desinstalar

```bash
sudo pacman -R atril-teleprompter
```

Los guiones y la sesión del usuario se conservan en
`~/.local/state/atril-teleprompter/` (o bajo `XDG_STATE_HOME`).

## Distribución y alcance

Este es un paquete del proyecto, publicado desde sus repositorios. **No
está publicado en AUR ni pertenece a los repositorios oficiales de Arch**.
Se proporciona la receta para que cualquiera pueda revisarla y reconstruirlo.
No se garantiza la compatibilidad con todas las distribuciones derivadas.
