# NextVPN для Linux

Версия NextVPN на GTK 4 и libadwaita для Fedora, CachyOS / Arch, NixOS, Ubuntu и
других дистрибутивов. Тот же движок, те же серверы и те же возможности, что у
версии для Windows.

<p align="center">
  <img src="../.github/screenshot-linux-light.png" alt="NextVPN для Linux" width="720">
</p>

## Те же серверы, что и у Windows-версии

Linux-версия запускает тот же движок **psiphon-tunnel-core** и читает те же файлы
из [`engine/`](../engine): `base.config` (идентификатор спонсора, канал
распространения, ключи подписи) и встроенный список серверов `server_list.dat`.
Эти поля передаются движку байт-в-байт, ничего не меняется. Серверная сеть та же.

Серверы Psiphon различают клиентов по началу поля `ClientPlatform`: всё, что
начинается с `Windows`, получает настройки для Windows, всё остальное — «Other».
Поэтому по умолчанию Linux-версия представляется серверам так же, как
Windows-версия (`Windows_<версия>_NextVPN`), и получает от них те же тактики,
протоколы и стартовые страницы. В **Настройки → Подключение → «Представляться
серверам как»** можно выбрать честное `Linux`.

## Установка

### Готовые пакеты

Из [релиза для Linux](https://github.com/Just-ElC/NextVPN/releases/tag/v1.0.0-linux):

| Система | Файл | Команда |
|---|---|---|
| Fedora 40+ | [nextvpn-1.0.0-1.x86_64.rpm](https://github.com/Just-ElC/NextVPN/releases/download/v1.0.0-linux/nextvpn-1.0.0-1.x86_64.rpm) | `sudo dnf install ./nextvpn-1.0.0-1.x86_64.rpm` |
| CachyOS, Arch, EndeavourOS, Manjaro | [nextvpn-1.0.0-1-x86_64.pkg.tar.zst](https://github.com/Just-ElC/NextVPN/releases/download/v1.0.0-linux/nextvpn-1.0.0-1-x86_64.pkg.tar.zst) | `sudo pacman -U nextvpn-1.0.0-1-x86_64.pkg.tar.zst` |
| Ubuntu 24.04+, Debian 13+, Mint 22+ | [nextvpn_1.0.0-1_amd64.deb](https://github.com/Just-ElC/NextVPN/releases/download/v1.0.0-linux/nextvpn_1.0.0-1_amd64.deb) | `sudo apt install ./nextvpn_1.0.0-1_amd64.deb` |

Ниже — как собрать то же самое из исходников.

### Fedora

```sh
sudo dnf install rpm-build meson gettext desktop-file-utils appstream gtk4-devel glib2-devel
linux/packaging/fedora/build-rpm.sh
sudo dnf install ~/rpmbuild/RPMS/x86_64/nextvpn-*.rpm
```

### CachyOS, Arch, EndeavourOS, Manjaro

```sh
cd linux/packaging/arch
makepkg -si
```

### NixOS

Запустить без установки:

```sh
nix run github:Just-ElC/NextVPN
```

Или добавить в конфигурацию (flake):

```nix
{
  inputs.nextvpn.url = "github:Just-ElC/NextVPN";

  outputs = { nixpkgs, nextvpn, ... }: {
    nixosConfigurations.my-pc = nixpkgs.lib.nixosSystem {
      modules = [
        nextvpn.nixosModules.default
        { programs.nextvpn.enable = true; }
      ];
    };
  };
}
```

Модуль заодно включает `programs.dconf`: без него системный прокси GNOME/GTK не
доходит до других программ на Plasma и в тайловых оконных менеджерах. Пакет
также доступен как `nextvpn.packages.<system>.nextvpn` и через
`nextvpn.overlays.default`. На aarch64 движок собирается из исходников той же
ревизии.

### Ubuntu, Debian

```sh
sudo apt install meson gettext dpkg-dev
linux/packaging/debian/build-deb.sh
sudo apt install ./nextvpn_1.0.0-1_amd64.deb
```

### Любой другой дистрибутив (openSUSE и т.д.)

```sh
linux/install.sh --deps     # поставить недостающие пакеты (спросит sudo)
linux/install.sh            # установить для себя в ~/.local, без прав администратора
```

`linux/install.sh --system` ставит для всех в `/usr/local`,
`linux/install.sh --uninstall` удаляет (настройки сохраняются).

Без установки, прямо из репозитория: `linux/run.sh`.

**Что нужно:** Python 3.10+, PyGObject и pycairo, GTK 4.10+, libadwaita 1.4+;
для сборки — meson и gettext.

## Как пользоваться

1. Нажмите большую круглую кнопку.
2. Дождитесь надписи **«Подключено»** — рабочий стол уже ходит через туннель.
3. Другая страна — вкладка **«Локации»**.
4. Нажмите кнопку ещё раз, чтобы отключиться.

Окно можно закрыть — приложение останется в области уведомлений (трее).

### Какие программы идут через туннель

На время подключения NextVPN включает **системный прокси** и возвращает ваши
прежние настройки после отключения (и после аварийного завершения — при
следующем запуске):

| Где | Что меняется | Кто это читает |
|---|---|---|
| GNOME, Cinnamon, Budgie, любые GTK/GIO-программы | GSettings `org.gnome.system.proxy` | Firefox («использовать системные настройки прокси», так по умолчанию), Chrome/Chromium/Brave/Edge, программы GNOME |
| KDE Plasma | `~/.config/kioslaverc`, `[Proxy Settings]` | программы KDE, Chromium-браузеры в Plasma |

Пока туннель переподключается (смена страны, обрыв связи), прокси **не
снимается**, чтобы трафик не ушёл мимо туннеля.

Терминал и консольные программы читают только переменные окружения. На главной
странице у «Локального прокси» есть кнопка копирования — она даёт готовую
команду `export http_proxy=… https_proxy=… all_proxy=…` для терминала.
Локальные порты можно зафиксировать в настройках, чтобы прописать их в других
программах вручную.

### Трей

Значок в трее работает по протоколу StatusNotifierItem: KDE Plasma, XFCE,
Cinnamon, Budgie, LXQt, waybar — сразу. В **GNOME** нужно расширение
AppIndicator (в Fedora — `gnome-shell-extension-appindicator`, в Ubuntu уже
включено). Без трея закрытие окна завершает программу.

Левый щелчок по значку — показать/скрыть окно, средний — подключить/отключить,
правый — меню.

### Командная строка

```
nextvpn                 открыть окно (или показать уже запущенное)
nextvpn --minimised     запустить в трее
nextvpn --connect       подключить
nextvpn --disconnect    отключить
nextvpn --toggle        подключить или отключить
nextvpn --quit          отключить и закрыть запущенную копию
```

Работает всегда одна копия: повторный запуск передаёт команду уже запущенной.
Удобно для горячих клавиш рабочего стола.

## Где что лежит

| | |
|---|---|
| `~/.config/nextvpn/settings.json` | настройки |
| `~/.local/share/nextvpn/` | данные движка, сгенерированный конфиг, резервная копия настроек прокси |
| `~/.config/autostart/io.github.just_elc.NextVPN.desktop` | автозапуск (если включён) |

Программа ничего не пишет вне этих мест и никогда не скачивает замену самой себе.

## Разработка

```sh
linux/run.sh                                  # запустить из исходников
cd linux && python3 -m unittest discover -s tests -t .   # тесты
meson setup _build && meson test -C _build    # то же через meson, с проверкой .desktop и metainfo
```

Тесты движка используют фейковый движок с тем же протоколом. С настоящим:
`NEXTVPN_REAL_ENGINE_TEST=1`. Настоящее подключение к сети Psiphon с запросом
через туннель: `python3 linux/tools/connect-check.py`. CI
(`.github/workflows/linux.yml`) делает всё это на каждом PR, собирает пакеты для
всех дистрибутивов, а по тегу `v*-linux` или при ручном запуске с параметром
`release_tag` публикует их релизом (во втором случае workflow сам создаёт тег). Тесты трея и view-model проверяют D-Bus и нужно
запускать под `dbus-run-session`.

| Каталог | |
|---|---|
| `nextvpn/core/` | всё, кроме интерфейса: движок, конфиг, системный прокси, автозапуск — без GTK |
| `nextvpn/ui/` | интерфейс на GTK 4 / libadwaita, трей, уведомления |
| `engine/` | Linux-сборка движка (общие `base.config` и `server_list.dat` — в `/engine`) |
| `po/` | переводы |
| `packaging/` | Fedora, Arch, Debian, Nix, архив исходников, заметки к релизу |
| `tools/` | сборка движка из исходников, проверка подключения к сети Psiphon |

Переменные окружения: `NEXTVPN_ENGINE` — путь к другому движку,
`NEXTVPN_ENGINE_DIR` — каталог с другими `base.config` и `server_list.dat`.
