## NextVPN для Linux

Первая версия для Linux: GTK 4 и libadwaita, **те же серверы** и все те же
возможности, что у версии для Windows. Одна кнопка, выбор страны, трей,
автозапуск, светлая и тёмная тема, интерфейс на русском.

<img src="https://raw.githubusercontent.com/Just-ElC/NextVPN/main/.github/screenshot-linux-light.png" alt="NextVPN для Linux" width="720">

### Установка

| Система | Файл | Команда |
|---|---|---|
| **Fedora** 40+ | `nextvpn-1.0.0-1.x86_64.rpm` | `sudo dnf install ./nextvpn-1.0.0-1.x86_64.rpm` |
| **CachyOS, Arch, EndeavourOS, Manjaro** | `nextvpn-1.0.0-1-x86_64.pkg.tar.zst` | `sudo pacman -U nextvpn-1.0.0-1-x86_64.pkg.tar.zst` |
| **Ubuntu** 24.04+, **Debian** 13+, **Linux Mint** 22+ | `nextvpn_1.0.0-1_amd64.deb` | `sudo apt install ./nextvpn_1.0.0-1_amd64.deb` |
| **NixOS** | — | `nix run github:Just-ElC/NextVPN/v1.0.0-linux` |
| Любой другой | `NextVPN-1.0.0-linux.tar.gz` | распаковать, затем `linux/install.sh --deps && linux/install.sh` |

После установки NextVPN появится в меню приложений.

### Что важно знать

- Подключение к сети Psiphon проверено автоматически при сборке этого релиза:
  туннель поднимается с теми же `base.config` и списком серверов, что у
  Windows-версии, и через него проходит трафик.
- На время подключения включается системный прокси GNOME и KDE Plasma — его
  используют браузеры и большинство программ. Ваши настройки возвращаются после
  отключения. Для терминала на главной есть кнопка с готовой командой `export`.
- В **GNOME** значок в трее появится только с расширением AppIndicator
  (`gnome-shell-extension-appindicator`).
- Сборки для x86_64. Для aarch64 используйте flake (`nix run`) или соберите
  движок скриптом `linux/tools/build-engine.sh`.

Подробности — в [linux/README.md](https://github.com/Just-ElC/NextVPN/blob/main/linux/README.md).
Контрольные суммы — в `SHA256SUMS`.

<sub>Работает на открытом движке [psiphon-tunnel-core](https://github.com/Psiphon-Labs/psiphon-tunnel-core) (GPLv3).
NextVPN — независимое приложение, не связано с Psiphon Inc.</sub>
