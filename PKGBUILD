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
  "cable.png::https://raw.githubusercontent.com/magillos/Cable/master/cable_cream.png"
  "cable.desktop::https://raw.githubusercontent.com/magillos/Cable/master/cable.desktop"
)
sha256sums=('a89c3448b94e5443db14cef9568331b4f5b447db78910fa2c153c55ef7c02218' 'f91f2f731cd92e6aa4b2dcab43c1a8244e809f4d0f571e8cd96881392f1bd92e' '3e34bab8b77a313d59c24abdc3845c1f9f25590122d9918e9fa1f0c3a3742e55' 'a81f95f4396376a9027b53709ec0d6111f65efa4908e1414961502d11814837a')

build() {
  cd "$srcdir"
  python setup.py build
}

package() {
  cd "$srcdir"
  python setup.py install --root="$pkgdir/" --optimize=1

  # Install the icon
  install -Dm644 "$srcdir/cable_cream.png" "$pkgdir/usr/share/pixmaps/cable_cream.png"

  # Install the desktop entry
  install -Dm644 "$srcdir/cable.desktop" "$pkgdir/usr/share/applications/cable.desktop"
}


