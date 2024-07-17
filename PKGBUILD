# Maintainer: Your Name <your.email@example.com>
pkgname=cable
pkgver=0.1.0
pkgrel=1
pkgdesc="A PyQt5 application for managing cables"
arch=('any')
url="https://github.com/magillos/Cable"
license=('MIT')  # Adjust based on the actual license if different
depends=('python' 'python-pyqt5')
makedepends=('python-setuptools')
source=(
  "Cable.py::https://raw.githubusercontent.com/magillos/Cable/master/Cable.py"
  "setup.py::https://raw.githubusercontent.com/magillos/Cable/master/setup.py"
)
sha256sums=('SKIP' 'SKIP')  # Update with actual checksums if needed

build() {
  cd "$srcdir"
  python setup.py build
}

package() {
  cd "$srcdir"
  python setup.py install --root="$pkgdir/" --optimize=1
}

# vim:set ts=2 sw=2 et:
