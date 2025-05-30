# Cable
PyQT GUI application to dynamically modify Pipewire and Wireplumber settings at runtime, such as quantum, sample rate, latency offset, services restart and more.
It features side-by-side and graph style connections managers (uses Python Jack Client so will not list Pipewire items), pw-top wrapper, simple ALSA mixer and jack_delay GUI. 


If you wonder what Latency Offset option does, look [here](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html#alsa-extra-latency-properties). 



To run, clone repository and start with `python Cable.py`. You will need python jack client, see [here](https://pypi.org/project/JACK-Client/0.5.1/), python PyQT6, jack_delay (or jack-example-tools) and pyalsaaudio installed.

Various packages are also available in [releases](https://github.com/magillos/Cable/releases).

For AppImage you may want to place cable.desktop in ~/.local/share/applications/ directory, for better icon integration.
For auto-start to work with AppImage, enable Autostart in tray menu and edit Exec entry in ~/.config/autostart/cable-autostart.desktop to point to your AppImage executable (e.g. Exec=/location/on/disk/./Cable-0.9.4.AppImage --minimized).

You need Pipewire in version 1.0 or newer, for connections manager to work.

On Arch Linux, install using PKGBUILD or Arch package. App is also available on AUR.



![](https://github.com/magillos/Cable/blob/main/Cable.png)
![](https://github.com/magillos/Cable/blob/main/Cables.png)
![](https://github.com/magillos/Cable/blob/main/graph.png)
![](https://github.com/magillos/Cable/blob/main/pw-top.png)
![](https://github.com/magillos/Cable/blob/main/mixer.png)
![](https://github.com/magillos/Cable/blob/main/latency.png)
![](https://github.com/magillos/Cable/blob/main/visibility.png)


Icon comes from [here](https://game-icons.net/1x1/delapouite/jack-plug.html) and is licenced under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
The app was made with heavy usage of various LLMs.
