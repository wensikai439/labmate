# ARM 工具链

原环境为 Ubuntu 24.04、GCC/G++ 13.3.0 arm-linux-gnueabihf，binutils 2.42、armhf glibc 2.39。安装包名称、版本、大小与 SHA-256 记录于 [toolchain_packages.json](toolchain_packages.json)。

在 Ubuntu 工作站按清单取得对应发行版 deb，并核对 SHA-256。例如：

```sh
apt-get download 'gcc-13-arm-linux-gnueabihf=13.3.0-6ubuntu2~24.04.1cross1'
```

把 GCC、G++、binutils、libc、libstdc++ 等 deb 用 `dpkg-deb -x package.deb "$V81/tools/cross"` 解压至同一目录。应存在 `usr/bin/arm-linux-gnueabihf-g++-13`。变量定义与其余依赖见[构建流程](README.md)。安装包未随仓库分发；复编译需要取得清单所列依赖。
