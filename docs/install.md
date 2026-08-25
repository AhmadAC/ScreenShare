# Installation

Latest Version: **GITHUB_VERSION**

Before starting ScreenShare you may read [Configuration](config.md).

!> TLS is required for ScreenShare to work. Either enable TLS inside ScreenShare or 
   use a reverse proxy to serve ScreenShare via TLS.

## Docker

Setting up ScreenShare with docker is pretty easy, you basically just have to start the docker container, and you are ready to go:

[ghcr.io/ScreenShare/server](https://github.com/orgs/ScreenShare/packages/container/package/server) and
[ScreenShare/server](https://hub.docker.com/r/ScreenShare/server)
docker images are multi-arch docker images.
This means the image will work for `amd64`, `i386`, `ppc64le` (power pc), `riscv64`, `arm64`, `armv7` (Raspberry PI) and `armv6`.

By default, ScreenShare runs on port 5050.

?> Replace `EXTERNALIP` with your external IP. One way to find your external ip is with ipify.
   `curl 'https://api.ipify.org'`

```bash
$ docker run --net=host -e ScreenShare_EXTERNAL_IP=EXTERNALIP ghcr.io/ScreenShare/server:GITHUB_VERSION
```

**docker-compose.yml**
```yaml
services:
  ScreenShare:
    image: ghcr.io/ScreenShare/server:GITHUB_VERSION
    network_mode: host
    environment:
      ScreenShare_EXTERNAL_IP: "EXTERNALIP"
```

If you don't want to use the host network, then you can configure docker like this:

<details><summary>(Click to expand)</summary>
<p>

!> ScreenShare may not work correctly when deploying it in docker without `network_mode: host`.
   See [#226](https://github.com/ScreenShare/server/issues/226)

```bash
$ docker run -it \
    -e ScreenShare_EXTERNAL_IP=EXTERNALIP \
    -e ScreenShare_TURN_PORT_RANGE=50000:50200 \
    -p 5050:5050 \
    -p 3478:3478 \
    -p 50000-50200:50000-50200/udp \
    ScreenShare/server:GITHUB_VERSION
```

#### docker-compose.yml

```yml
version: "3.7"
services:
  ScreenShare:
    image: ghcr.io/ScreenShare/server:GITHUB_VERSION
    ports:
      - 5050:5050
      - 3478:3478
      - 50000-50200:50000-50200/udp
    environment:
      ScreenShare_EXTERNAL_IP: "192.168.178.2"
      ScreenShare_TURN_PORT_RANGE: "50000:50200"
```

</p>
</details>

## Binary

### Supported Platforms:

- linux_amd64 (64bit)
- linux_i386 (32bit)
- armv7 (32bit used for Raspberry Pi)
- armv6
- arm64 (ARMv8)
- ppc64
- ppc64le
- windows_i386.exe (32bit)
- windows_amd64.exe (64bit)

Download the zip with the binary for your platform from [ScreenShare/server Releases](https://github.com/ScreenShare/server/releases).

```bash
$ wget https://github.com/ScreenShare/server/releases/download/vGITHUB_VERSION/ScreenShare_GITHUB_VERSION_{PLATFORM}.tar.gz
```

Unzip the archive.

```bash
$ tar xvf ScreenShare_GITHUB_VERSION_{PLATFORM}.tar.gz
```

Make the binary executable (linux only).

```bash
$ chmod +x ScreenShare
```

Execute ScreenShare:

```bash
$ ./ScreenShare
# on windows
$ ScreenShare.exe
```

## Arch-Linux(aur)

!> Maintenance of the AUR Packages is not performed by the ScreenShare team.
   You should always check the PKGBUILD before installing an AUR package.

ScreenShare's latest release is available in the AUR as [ScreenShare-server](https://aur.archlinux.org/packages/ScreenShare-server/) and [ScreenShare-server-bin](https://aur.archlinux.org/packages/ScreenShare-server-bin/).
The development-version can be installed with [ScreenShare-server-git](https://aur.archlinux.org/packages/ScreenShare-server-git/).

## FreeBSD

!> Maintenance of the FreeBSD Package is not performed by the ScreenShare team.
   Check yourself, if you can trust it.

```bash
$ pkg install ScreenShare
```

## Source

[See Development#build](development.md#build)
