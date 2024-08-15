### Maintainer: Your Name <your.email@example.com>
pkgname=cable
pkgver=0.1.4
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
  "cable.png::https://raw.githubusercontent.com/magillos/Cable/master/Cable.png"
  "cable.desktop::https://raw.githubusercontent.com/magillos/Cable/master/cable.desktop"
)
sha256sums=('e0355e07ba7d8014e061cd313d8f34714bcf0f48e1cc031c08d09a0e83cd0ff1' '2dce3e1c296588c4fab3e092dada427e8a3b09fab046679c06af46aa835a3688' '32225b468bf6a72b0a9b1680b97c8e452d2358edbf30de3a479dc9b5bb796d2f' '6b40587929ed9739782dbdaccaa48d14dbae2ed427022acf1875a287e5b1b57e')  

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


