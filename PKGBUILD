# Maintainer: Your Name <your.email@example.com>
pkgname=cable
pkgver=0.1.0
pkgrel=1
pkgdesc="A PyQt5 application to dynamically modify Pipewire and Wireplumber settings"
arch=('any')
url="https://github.com/magillos/Cable"
license=('MIT')  # Adjust based on the actual license if different
depends=('python' 'python-pyqt5')
makedepends=('python-setuptools')
source=(
  "Cable.py::https://raw.githubusercontent.com/magillos/Cable/master/Cable.py"
  "setup.py::https://raw.githubusercontent.com/magillos/Cable/master/setup.py"
  "cable.png::https://raw.githubusercontent.com/magillos/Cable/master/cable.png"
  "cable.desktop::https://raw.githubusercontent.com/magillos/Cable/master/cable.desktop"
)
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP')  # Update with actual checksums if needed

build() {
  cd "$srcdir"
  python setup.py build
}

package() {
  cd "$srcdir"
  python setup.py install --root="$pkgdir/" --optimize=1

  # Install the icon
  install -Dm644 "$srcdir/cable.png" "$pkgdir/usr/share/pixmaps/cable.png"

  # Install the desktop entry
  install -Dm644 "$srcdir/cable.desktop" "$pkgdir/usr/share/applications/cable.desktop"
}

# vim:set ts=2 sw=2 et:
