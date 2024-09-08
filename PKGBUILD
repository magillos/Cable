### Maintainer: Your Name <your.email@example.com>
pkgname=cable
pkgver=0.1.5
pkgrel=1
pkgdesc="A PyQt5 application to dynamically modify Pipewire and Wireplumber settings"
arch=('any')
url="https://github.com/magillos/Cable"
license=('GPL-3.0')  
depends=('python' 'python-pyqt5')
makedepends=('python-setuptools')
source=(
  "Cable.py::https://raw.githubusercontent.com/magillos/Cable/master/Cable.py"
  "setup.py::https://raw.githubusercontent.com/magillos/Cable/master/setup.py"
  "jack-plug.svg::https://raw.githubusercontent.com/magillos/Cable/master/jack-plug.svg"
  "cable.desktop::https://raw.githubusercontent.com/magillos/Cable/master/cable.desktop"
)
sha256sums=('SKIP') #'8c7e2e79153bd4099dfab91899d313105224e8d9fa86ea4f28bc81fd09458f90' 'f91f2f731cd92e6aa4b2dcab43c1a8244e809f4d0f571e8cd96881392f1bd92e' '0f44d6959d8703ca234050d613b9933ee64d1375d596d9638430b26909f2f84c' '9a47a9ffb4c3101c8b1ebbf06676610345aac2bcd13b4967020ace960f384dc6')

build() {
  cd "$srcdir"
  python setup.py build
}

package() {
  cd "$srcdir"
  python setup.py install --root="$pkgdir/" --optimize=1

  # Install the icon
  install -Dm644 "$srcdir/jack-plug.svg" "$pkgdir/usr/share/pixmaps/jack-plug.svg"

  # Install the desktop entry
  install -Dm644 "$srcdir/cable.desktop" "$pkgdir/usr/share/applications/cable.desktop"
}


