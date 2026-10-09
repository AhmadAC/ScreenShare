# Config

!> TLS is required for ScreenShare to work. Either enable TLS inside ScreenShare or 
   use a reverse proxy to serve ScreenShare via TLS.

ScreenShare tries to obtain config values from different locations in sequence. 
Properties will never be overridden. Thus, the first occurrence of a setting will be used.

#### Order

* Environment Variables
* `ScreenShare.config.local` (in same path as the binary)
* `ScreenShare.config` (in same path as the binary)
* `$HOME/.config/ScreenShare/server.config`
* `/etc/ScreenShare/server.config`

#### Config Example

[ScreenShare.config.example](https://raw.githubusercontent.com/ScreenShare/server/master/ScreenShare.config.example ':include :type=code ini')
