# Maintainer: Your Name <your.email@example.com>
pkgname=cable
pkgver=0.1.0
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
sha256sums=('00f22cab8102a987075dcc7cd81121bebe0bb909e7055a07d91fddd5b5805db5' 'b4f478c5fd01a10370eed139db789f2edb20a38f89d30d75e741acaf1ccd1e36' '32225b468bf6a72b0a9b1680b97c8e452d2358edbf30de3a479dc9b5bb796d2f' '937750ed9c06f862d41f23c35b5732e8b2a6ecfa000f694e7d119a78da56e71d')  

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


