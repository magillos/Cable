# Cable
PyQT GUI application to dynamically modify [PipeWire](https://PipeWire.org/) and [WirePlumber](https://pipewire.pages.freedesktop.org/wireplumber/) settings at runtime, such as quantum, sample rate, audio profiles, latency offset, services restart and more.
It features side-by-side, MIDI matrix and graph style connections managers (uses Python Jack Client so will not list Pipewire items), pw-top wrapper, simple ALSA mixer and jack_delay GUI. 

You need Pipewire in version 1.0 or newer, for connections manager to work.

If you wonder what Latency Offset option does, look [here](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html#alsa-extra-latency-properties). 


## Run
To run, clone repository and start with `python Cable.py`. You will need python jack client, see [here](https://pypi.org/project/JACK-Client/), python PyQT6, jack_delay (or jack-example-tools), pyalsaaudio and aj-snapshot installed:
`sudo apt install python3-jack-client libqt6svg6 jack-delay python3-pyqt6 python3-dbus python3-requests python3-packaging aj-snapshot python3-alsaaudio pipewire-jack python3-graphviz` 


## Install
Various packages are available in [releases](https://github.com/magillos/Cable/releases). 

On Arch Linux, install using PKGBUILD or with Arch package. App is also available on AUR. 

AppImage requires dependencies to be installed.

Flatpak requires Flathub repository: `flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo`.

With AppImage version 0.9.16, auto-start should work (toggle Autostart option off/on to recreate `.desktop` file).

Packaging files (Flatpak, AppImage, Debian) are in [cable-packaging](https://github.com/magillos/cable-packaging) repository.




## Screenshots

![](https://github.com/magillos/Cable/blob/main/Cable.png)
![](https://github.com/magillos/Cable/blob/main/Cables.png)
![](https://github.com/magillos/Cable/blob/main/graph.png)
![](https://github.com/magillos/Cable/blob/main/pw-top.png)
![](https://github.com/magillos/Cable/blob/main/mixer.png)
![](https://github.com/magillos/Cable/blob/main/latency.png)
![](https://github.com/magillos/Cable/blob/main/visibility.png)
![](https://github.com/magillos/Cable/blob/main/MIDI_Matrix.png)


## Notes
Icon comes from [here](https://game-icons.net/1x1/delapouite/jack-plug.html) and is licenced under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
The app was made with heavy usage of various LLMs.
