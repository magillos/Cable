### Maintainer: Your Name <your.email@example.com>

pkgname=cable
pkgver=0.4.1
pkgrel=1
pkgdesc="A PyQt5 application to dynamically modify Pipewire and Wireplumber settings"
arch=('any')
url="https://github.com/magillos/Cable"
license=('GPL-3.0')
depends=('python' 'python-pyqt5' 'python-jack-client')
makedepends=('python-setuptools')
source=(
  "Cable.py::https://raw.githubusercontent.com/magillos/Cable/master/Cable.py"
  "setup.py::https://raw.githubusercontent.com/magillos/Cable/master/setup.py"
  "jack-plug.svg::https://raw.githubusercontent.com/magillos/Cable/master/jack-plug.svg"
  "local.cable.Cable.desktop::https://raw.githubusercontent.com/magillos/Cable/master/local.cable.Cable.desktop"
  "connection-manager.py::https://raw.githubusercontent.com/magillos/Cable/master/connection-manager.py"
)

sha256sums=('0c4f754547bab62c183b80cad122d488343d2fb4cd429cabe10309c3600e9179'
            '7b8e0d226264db7075c076e169491d606077609f288915a3de1d44d7d3754b28'
            '5c3fa8b496c1a4a1918a2bfa2420cfa3ceedc93307d566a55c8f0835f3b33442'
            '8cff61b117863f5dee1f918cd28c15245c696fdb5a289c0b8b3afe8a3d11c22f'
            'e78db83621d2b38e167da34be7be2cf855e4ace2f470c4a9ccf6fb71673a95cb')


build() {
  cd "$srcdir"
  python setup.py build
}

package() {
  cd "$srcdir"
  python setup.py install --root="$pkgdir/" --optimize=1

  # Install the icon
  install -Dm644 "$srcdir/jack-plug.svg" "$pkgdir/usr/share/icons/hicolor/scalable/apps/jack-plug.svg"

  # Install the desktop entry
  install -Dm644 "$srcdir/local.cable.Cable.desktop" "$pkgdir/usr/share/applications/local.cable.Cable.desktop"

  # Create the /usr/share/cable directory if it doesn't exist
  install -d "$pkgdir/usr/share/cable"

  # Install connection-manager.py to /usr/share/cable
  install -D "$srcdir/connection-manager.py" "$pkgdir/usr/share/cable/connection-manager.py"
}
