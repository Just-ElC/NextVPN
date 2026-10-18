<p align="center">
  <img src=".github/logo.png" alt="NextVPN" width="150">
</p>

<div align="center">

# NextVPN

### Свободный интернет в один клик

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-Fedora%20%7C%20CachyOS%20%7C%20NixOS-F5A623?style=for-the-badge&logo=linux&logoColor=white)
![Бесплатно](https://img.shields.io/badge/Бесплатно-навсегда-1FA97B?style=for-the-badge)
![Release](https://img.shields.io/github/v/release/Just-ElC/NextVPN?style=for-the-badge&color=1FA97B&label=Версия)
![Downloads](https://img.shields.io/github/downloads/Just-ElC/NextVPN/total?style=for-the-badge&color=0078D4&label=Загрузок)

</div>

---

<div align="center">

## Скачать

[![Скачать для Windows](https://img.shields.io/badge/⬇%20%20Скачать%20для%20Windows-1FA97B?style=for-the-badge&logoColor=white)](https://github.com/Just-ElC/NextVPN/releases/latest/download/NextVPN-Setup-1.0.0.exe)

[Версия без установки](https://github.com/Just-ElC/NextVPN/releases/latest/download/NextVPN-1.0.0-win-x64.zip) · [все версии](https://github.com/Just-ElC/NextVPN/releases)

**Linux** (GTK 4): [Fedora · CachyOS / Arch · NixOS · Ubuntu и другие](#linux)

**Без регистрации · без подписки · без ограничений по трафику**

</div>

---

<div align="center">

<img src=".github/screenshot-light.png" alt="NextVPN" width="880">

</div>

---

## Установка

1. Скачайте и запустите файл.
2. Windows покажет синее окно — нажмите **«Подробнее»**, затем **«Выполнить в любом случае»**.
3. Если появится просьба установить **.NET 8** — согласитесь, поставьте его и запустите файл снова.
4. Нажмите **«Да»**.

Через несколько секунд **NextVPN** появится в меню «Пуск». Права администратора не нужны.

---

## Как пользоваться

1. Нажмите большую круглую кнопку.
2. Дождитесь надписи **Connected** — всё, интернет уже свободен. Ничего настраивать не нужно.
3. Хотите другую страну — откройте **Locations** и выберите из списка.
4. Нажмите кнопку ещё раз, чтобы отключиться.

Окно можно закрыть — приложение свернётся к часам в углу экрана и продолжит работать.

---

## Что умеет

| | |
|---|---|
| **Одна кнопка** | Никаких серверов, ключей и настроек — просто нажать |
| **Выбор страны** | Список стран с поиском, переключение на лету |
| **Работает во всех программах** | Браузеры и приложения подхватывают соединение сами |
| **Светлая и тёмная тема** | Подстраивается под оформление Windows |
| **Живёт в трее** | Не мешает, не занимает место на панели задач |
| **Автозапуск** | Может включаться вместе с Windows и сразу подключаться |
| **Скорость на виду** | Видно, сколько скачано, отдано и как долго вы онлайн |
| **Ничего лишнего** | Не показывает рекламу, не просит почту, не собирает данные |

---

<div align="center">

## Тёмная тема

<img src=".github/screenshot-dark.png" alt="NextVPN в тёмной теме" width="880">

</div>

---

<a id="linux"></a>

<div align="center">

## Linux

<img src=".github/screenshot-linux-light.png" alt="NextVPN для Linux" width="720">

</div>

Версия для Linux на GTK 4 и libadwaita: тот же движок, **те же серверы** и все те же
возможности — одна кнопка, выбор страны, трей, автозапуск, светлая и тёмная тема.
Системный прокси включается в GNOME и KDE Plasma. Подробности — в
[linux/README.md](linux/README.md).

| Система | Как установить |
|---|---|
| **Fedora** | `linux/packaging/fedora/build-rpm.sh`, затем `sudo dnf install ~/rpmbuild/RPMS/x86_64/nextvpn-*.rpm` |
| **CachyOS, Arch, Manjaro** | `cd linux/packaging/arch && makepkg -si` |
| **NixOS** | `nix run github:Just-ElC/NextVPN` или модуль `programs.nextvpn.enable = true` |
| **Ubuntu, Debian и другие** | `linux/install.sh --deps && linux/install.sh` — в домашнюю папку, без прав администратора |

---

## Частые вопросы

**Это бесплатно?**  
Да, полностью и без ограничений.

**Нужна регистрация?**  
Нет. Скачали, запустили, нажали кнопку.

**Почему Windows предупреждает при запуске?**  
Так происходит с любой небольшой программой без платного сертификата разработчика — он стоит денег и ежегодно продлевается. Нажмите «Подробнее» → «Выполнить в любом случае».

**Куда всё установится?**  
В вашу личную папку пользователя. Другие пользователи компьютера ничего не заметят, права администратора не нужны.

**Как удалить?**  
«Параметры» → «Приложения» → «Установленные приложения» → **NextVPN** → «Удалить».

**Работает ли во всех программах?**  
Браузеры и большинство приложений — сразу. Отдельные игры и программы, которые не смотрят на сетевые настройки Windows, могут ходить в обход.

**А в Linux?**  
Браузеры и программы, которые берут системный прокси GNOME или KDE, — сразу. Для терминала NextVPN даёт готовую команду с переменными прокси (кнопка у «Локального прокси»). В GNOME для значка в трее нужно расширение AppIndicator.

---

<div align="center">

## NextVPN

### Первая часть [NextOS](https://github.com/Just-ElC)

<sub>Работает на открытом движке [Psiphon](https://github.com/Psiphon-Labs/psiphon-tunnel-core) (лицензия GPLv3).<br>
NextVPN — независимое приложение, не связано с Psiphon Inc.</sub>

</div>
