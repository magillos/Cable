# Cable
PyQT GUI application to dynamically modify Pipewire and Wireplumber settings at runtime.
Now, with side by side connections manager. 


If you wonder what Latency option does, look [here](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html#alsa-extra-latency-properties). 




To run, download Cable.py, connection-manager.py and jack-plug.svg and put them all in the same directory and start with:
`python Cable.py`. You will need python jack client, see [here](https://pypi.org/project/JACK-Client/0.5.1/). 

Or use pyinstaller executable from [releases](https://github.com/magillos/Cable/releases). Make it executable with `chmod +x`.

For above, download and place local.cable.Cable.desktop in ~/.local/share/applications/ directory.

On Arch Linux, install using PKGBUILD or Arch package.


![](https://github.com/magillos/Cable/blob/main/Cable.png)
![](https://github.com/magillos/Cable/blob/main/Cables.png)

Icon comes from [here](https://game-icons.net/1x1/delapouite/jack-plug.html) and is licenced under [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
The app was made with heavy usage of various LLMs.
