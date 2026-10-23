## NextVPN 1.1.0 для Linux

<img src="https://raw.githubusercontent.com/Just-ElC/NextVPN/main/.github/screenshot-linux-light.png" alt="NextVPN для Linux" width="720">

### Что нового

- **Режим VPN: через туннель идёт всё.** Браузеры, Telegram, Discord, игры,
  терминал, DNS и IPv6 — в любом окружении, включая Hyprland (caelestia и другие
  оболочки на quickshell), Sway, niri и i3. Раньше там через туннель шли только
  немногие программы, читающие системный прокси. Интерфейс создаёт
  NetworkManager, пароль не нужен. После отключения, сбоя или `kill -9` сеть
  возвращается как была. Без NetworkManager работает прежний режим системного
  прокси.
- **Движок обновлён** до свежего upstream psiphon-tunnel-core (20 октября): там
  исправления in-proxy подключений, TLS ECH и работы в сетях без IPv6. Сборка
  воспроизводима: CI пересобирает движок из исходников и сверяет байт в байт.
- **Значок в трее** появляется в caelestia и других оболочках на quickshell, в
  том числе при запуске через `nix run`.
- **Нет синих плашек** со «стартовой страницей» и «версией 189» — это сообщения
  сети Psiphon для её собственного клиента; теперь они только в журнале.
- Если подключение через выбранную страну затянулось, NextVPN подскажет
  выбрать «Самая быстрая» — там серверов во много раз больше.

### Установка

| Система | Файл | Команда |
|---|---|---|
| **Fedora** 40+ | `nextvpn-1.1.0-1.x86_64.rpm` | `sudo dnf install ./nextvpn-1.1.0-1.x86_64.rpm` |
| **CachyOS, Arch, EndeavourOS, Manjaro** | `nextvpn-1.1.0-1-x86_64.pkg.tar.zst` | `sudo pacman -U nextvpn-1.1.0-1-x86_64.pkg.tar.zst` |
| **Ubuntu** 24.04+, **Debian** 13+, **Linux Mint** 22+ | `nextvpn_1.1.0-1_amd64.deb` | `sudo apt install ./nextvpn_1.1.0-1_amd64.deb` |
| **NixOS** | — | модуль `programs.nextvpn.enable = true` или `nix run github:Just-ElC/NextVPN/v1.1.0-linux` |
| Любой другой | `NextVPN-1.1.0-linux.tar.gz` | распаковать, затем `linux/install.sh --deps && linux/install.sh` |

После установки NextVPN появится в меню приложений.

### Что важно знать

- При сборке этого релиза CI проверил, что всё работает на настоящей сети
  Psiphon. В режиме прокси трафик идёт через локальный прокси. В режиме VPN
  обычный запрос и DNS уходят с адреса сервера Psiphon, в том числе при строгом
  `rp_filter`, как в файрволе NixOS. После отключения и после `kill -9`
  ничего не остаётся. Серверы, `base.config` и список серверов те же, что у
  Windows-версии.
- Режиму VPN нужен NetworkManager. Он есть в Fedora, CachyOS, Ubuntu и на
  большинстве десктопов NixOS (`networking.networkmanager.enable`). Режим
  переключается в «Настройки → Система».
- В **GNOME** значок в трее появится только с расширением AppIndicator
  (`gnome-shell-extension-appindicator`).
- Сборки для x86_64. Для aarch64 используйте flake (`nix run`) или соберите
  движок скриптом `linux/tools/build-engine.sh`.

Подробности — в [linux/README.md](https://github.com/Just-ElC/NextVPN/blob/main/linux/README.md).
Контрольные суммы — в `SHA256SUMS`.

<sub>Работает на открытом движке [psiphon-tunnel-core](https://github.com/Psiphon-Labs/psiphon-tunnel-core) (GPLv3).
NextVPN — независимое приложение, не связано с Psiphon Inc.</sub>
