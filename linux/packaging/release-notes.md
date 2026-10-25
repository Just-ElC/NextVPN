## NextVPN 1.1.1 для Linux

<img src="https://raw.githubusercontent.com/Just-ElC/NextVPN/main/.github/screenshot-linux-light.png" alt="NextVPN для Linux" width="720">

### Что нового

- **Закрытие окна закрывает программу.** Раньше на CachyOS, Arch с KDE и везде,
  где есть трей, кнопка закрытия только прятала окно, и NextVPN продолжал
  работать. Теперь он отключает туннель и выходит; окно исчезает сразу. Прежнее
  поведение — переключатель «Настройки → Запуск и окно → Оставаться в области
  уведомлений».
- **Анимации на NixOS.** Модуль `programs.nextvpn` и `overlays.default` теперь
  собирают программу из nixpkgs самой системы, чтобы GTK рисовал видеокартой с
  системными драйверами, а не процессором. В «Настройки → О программе →
  Отрисовка» и в журнале видно, как рисуется окно; если без видеокарты, там же
  написано, что делать. Для `nix run`:
  `nix run github:Just-ElC/NextVPN --override-input nixpkgs nixpkgs`.
- **Нет индикатора «Подключено»** в левом верхнем углу: состояние и так видно
  на главной странице.

Что было в 1.1.0: режим VPN, через который идёт весь трафик, в том числе на
Hyprland, Sway и других оконных менеджерах; движок со свежего upstream; значок в
трее на quickshell; никаких синих плашек от сети Psiphon.

### Установка

| Система | Файл | Команда |
|---|---|---|
| **Fedora** 40+ | `nextvpn-1.1.1-1.x86_64.rpm` | `sudo dnf install ./nextvpn-1.1.1-1.x86_64.rpm` |
| **CachyOS, Arch, EndeavourOS, Manjaro** | `nextvpn-1.1.1-1-x86_64.pkg.tar.zst` | `sudo pacman -U nextvpn-1.1.1-1-x86_64.pkg.tar.zst` |
| **Ubuntu** 24.04+, **Debian** 13+, **Linux Mint** 22+ | `nextvpn_1.1.1-1_amd64.deb` | `sudo apt install ./nextvpn_1.1.1-1_amd64.deb` |
| **NixOS** | — | модуль `programs.nextvpn.enable = true` или `nix run github:Just-ElC/NextVPN/v1.1.1-linux` |
| Любой другой | `NextVPN-1.1.1-linux.tar.gz` | распаковать, затем `linux/install.sh --deps && linux/install.sh` |

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
  переключается в «Настройки → Подключение».
- В **GNOME** значок в трее появится только с расширением AppIndicator
  (`gnome-shell-extension-appindicator`).
- Сборки для x86_64. Для aarch64 используйте flake (`nix run`) или соберите
  движок скриптом `linux/tools/build-engine.sh`.

Подробности — в [linux/README.md](https://github.com/Just-ElC/NextVPN/blob/main/linux/README.md).
Контрольные суммы — в `SHA256SUMS`.

<sub>Работает на открытом движке [psiphon-tunnel-core](https://github.com/Psiphon-Labs/psiphon-tunnel-core) (GPLv3).
NextVPN — независимое приложение, не связано с Psiphon Inc.</sub>
