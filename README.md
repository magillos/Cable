# Cable
PyQT GUI application to dynamically modify Pipewire and Wireplumber settings at runtime.

I wanted to make my workflow bit easier so I asked Claude 3.5 Sonnet to write it for me, and it did. You shouldn't need to restart Pipewire or Wireplumber after changing any of the setting in the app. These buttons are there for convenience. Devices, nodes and settings should now reload after services restart. ~~If you click any of these buttons, you'll need to restart the app because the IDs of devices and nodes will change.~~ 

If you wonder what Latency option does, look [here](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/alsa.html#alsa-extra-latency-properties). 




To start just run:
`python Cable.py` or install using PKGBUILD.

![](https://github.com/magillos/Cable/blob/main/Cable.png)

