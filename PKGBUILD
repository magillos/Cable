# Maintainer: Your Name <your.email@example.com>
pkgname=cable
pkgver=0.1.2
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
  "cable.png::https://raw.githubusercontent.com/magillos/Cable/master/cable.png"
  "cable.desktop::https://raw.githubusercontent.com/magillos/Cable/master/cable.desktop"
)
sha256sums=('4e0d70425e3ca91415d66b4cf3c6c41a0953ad659b3e70934d54d1e428f3e1e4' 'b3777ee1751f364a6a28b93cf03227adcc7ede786748ab6a8d7a07c724d91faf' '1f8802ee2f4af7e77b6a5d6051eb685aa5456420ee4271ab56f4144182f1215e' '6b40587929ed9739782dbdaccaa48d14dbae2ed427022acf1875a287e5b1b57e')  

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


