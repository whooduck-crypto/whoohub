<p align="center">
  <img src="data/icons/io.github.whooduck_crypto.Whoohub.svg" width="128" alt="значок whoohub">
</p>

<h1 align="center">whoohub</h1>

<p align="center">
  <b>Один магазин приложений для Arch Linux: официальные репозитории, Flathub, AUR и AppImage в одном месте.</b>
  <br>
  Выглядит и работает как магазин в телефоне. Любая программа ставится одной кнопкой.
</p>

<p align="center">
  <a href="https://github.com/whooduck-crypto/whoohub/releases/latest"><img alt="Последний выпуск" src="https://img.shields.io/github/v/release/whooduck-crypto/whoohub?label=release"></a>
  <a href="LICENSE"><img alt="Лицензия: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
  <img alt="Для систем на базе Arch" src="https://img.shields.io/badge/for-Arch%20Linux-1793d1">
  <img alt="GTK 4 + libadwaita" src="https://img.shields.io/badge/GTK%204-libadwaita-4a86cf">
  <br>
  <a href="README.md">Read in English</a>
</p>

<p align="center">
  <img src="docs/screenshots/ru/home.png" width="820" alt="whoohub: главная с баннером «Программа дня» и полками">
</p>

## Зачем

В Arch программы живут в четырёх местах, и у каждого свой инструмент: `pacman` для репозиториев,
`flatpak` для Flathub, помощник для AUR и AppImage, которые скачивают вручную. Если не знаешь заранее,
где лежит нужная программа, найти её — отдельная задача.

whoohub ищет сразу везде и показывает **каждую программу один раз** — с большой кнопкой
**«Установить»**, которая просто работает, как в магазине на телефоне. Источник выбирается сам (и его
можно поменять на странице программы, с понятным объяснением разницы).

## Скриншоты

| Страница программы | Игры | Поиск (с результатами из AUR) |
|---|---|---|
| <img src="docs/screenshots/ru/app.png" alt="Страница программы"> | <img src="docs/screenshots/games.png" alt="Вкладка «Игры»"> | <img src="docs/screenshots/search.png" alt="Поиск"> |

## Возможности

- **Как магазин в телефоне.** Главная с баннером «Программа дня» и полками (Популярное, Игры, Для
  творчества, Для работы, Интернет и общение, Полезные утилиты), вкладки «Игры», «Программы»,
  «Библиотека» с твоими программами и поиск сверху.
- **Одна кнопка у каждой программы.** «Установить» / «Открыть» прямо в любом списке — без захода на страницу.
- **Одна страница на программу.** Firefox из репозиториев и с Flathub — это одна программа; внизу
  страницы, в «Откуда установить», можно выбрать источник, с объяснением простыми словами.
- **Репозитории (pacman)** — установка через графическое окно пароля polkit, без терминала.
- **Flathub** — установка в твой профиль, без пароля.
- **AUR** — поиск онлайн; перед сборкой whoohub показывает PKGBUILD и предупреждает, ставит недостающие
  зависимости из репозиториев и собирает пакет через `makepkg`.
- **AppImage** — каталог AppImageHub; whoohub скачивает последний стабильный выпуск с GitHub автора в
  `~/Applications` и добавляет ярлык в меню.
- **Обновляется сам.** Раз в сутки whoohub проверяет, не вышла ли новая версия, и предлагает обновиться
  прямо из программы — после сверки контрольной суммы от GitHub. Проверку можно отключить в меню.
- Светлая и тёмная тема по настройке системы. Английский и русский; другие языки — welcome.

## Установка

### Быстрая установка (рекомендуется)

```sh
curl -fsSL https://raw.githubusercontent.com/whooduck-crypto/whoohub/main/install.sh | sh
```

[Скрипт](install.sh) скачивает пакет последнего выпуска, сверяет его с контрольной суммой от GitHub и
ставит через pacman (sudo спросит пароль, зависимости pacman поставит сам). Его можно сначала прочитать.
Дальше whoohub обновляется сам, прямо из программы.

### Вручную

Скачай `whoohub-…-any.pkg.tar.zst` со страницы [Releases](https://github.com/whooduck-crypto/whoohub/releases) и выполни:

```sh
sudo pacman -U ~/Загрузки/whoohub-*-any.pkg.tar.zst
```

(`pacman -U <ссылка>` прямо из интернета не сработает: для пакетов по ссылке pacman требует подпись, а
пакеты whoohub не подписаны.)

### Собрать пакет самому

```sh
git clone https://github.com/whooduck-crypto/whoohub.git
cd whoohub/packaging/aur
makepkg -si
```

Пакет в AUR появится позже — регистрация в AUR сейчас закрыта.

### Из исходников

```sh
sudo pacman -S --needed python python-gobject gtk4 libadwaita polkit archlinux-appstream-data gettext
# по желанию: flatpak (Flathub), git + base-devel (AUR)
git clone https://github.com/whooduck-crypto/whoohub.git
cd whoohub
make run                       # запустить прямо из папки с исходниками
sudo make install              # установить в /usr/local
```

Нужен запущенный **агент polkit** (он есть в любом окружении рабочего стола; в голом оконном менеджере
запусти, например, `polkit-gnome`) — он показывает окно пароля при установке из репозиториев.

## Чем отличается от других

| | Репозитории | Flathub | AUR | AppImage | Одна страница на программу |
|---|:-:|:-:|:-:|:-:|:-:|
| **whoohub** | ✓ | ✓ | ✓ | ✓ | ✓ |
| GNOME Software | ✓ | ✓ | — | — | ✓ |
| KDE Discover | ✓ | ✓ | — | — | — |
| pamac (Manjaro) | ✓ | ✓ | ✓ | — | — |

Ближайший родственник — pamac, и он гораздо зрелее: если он тебя устраивает, оставайся на нём. Отличие
whoohub — более простой интерфейс в духе магазина в телефоне, AppImage и то, что каждая программа
показывается один раз, откуда бы она ни была.

## Как это устроено

| Источник | Каталог | Установка | Root |
|---|---|---|---|
| Репозитории | AppStream из `archlinux-appstream-data` | `pkexec pacman -S` | окно polkit |
| Flathub | AppStream Flathub (remote для пользователя) | `flatpak install --user` | нет |
| AUR | онлайн-поиск через AUR RPC | `git clone` → `makepkg` → `pkexec pacman -U` | окно polkit |
| AppImage | [фид AppImageHub](https://appimage.github.io/) | выпуски на GitHub → `~/Applications` | нет |

Программы из репозиториев и с Flathub склеиваются по AppStream-идентификатору, AppImage — по названию,
если совпадение однозначное. Общий каталог хранится в `~/.cache/whoohub/catalog.sqlite` (SQLite + FTS5) и
пересобирается сам, когда меняется каталог какого-либо источника. whoohub никогда не использует `sudo`.

## Вопросы и ответы

**Это безопасно?**
Пакеты из репозиториев и Flatpak приходят из Arch и Flathub — ровно так же, как через `pacman` и
`flatpak`. Пакеты AUR и AppImage делают их авторы, а не Arch или Flathub; whoohub пишет об этом на каждой
такой странице и показывает скрипт сборки AUR до сборки. Права root — только через окно пароля polkit.
Сеть: кроме каталогов и файлов устанавливаемых программ, whoohub раз в сутки делает один запрос к API
GitHub за своим последним выпуском (никаких данных о тебе; отключается в меню).

**Работает на EndeavourOS, CachyOS, Garuda, Manjaro…?**
Сделан для Arch и систем на его базе. У Manjaro свои репозитории, которые отстают от Arch, а команда
Manjaro не советует AUR — запуститься whoohub там должен, но это не проверялось.

**А Ubuntu, Fedora, openSUSE?**
Пока нет. Части с Flathub и AppImage работали бы где угодно, а для пакетов дистрибутива нужна поддержка
PackageKit. Помощь приветствуется.

**Почему нет оценок и числа скачиваний?**
Ни один из источников (пока) не публикует их в пригодном виде.

**Кто это сделал?**
whoohub — хобби-проект [whooduck-crypto](https://github.com/whooduck-crypto). Большая часть кода
написана вместе с Claude, ИИ-ассистентом от Anthropic, — в коммитах это отмечено строкой
`Co-Authored-By`. Сообщения об ошибках очень приветствуются.

## Планы

- Обновления установленных программ, а не только самого whoohub
- Пакеты AUR, которые зависят от других пакетов AUR
- Пакет whoohub в AUR (когда там снова откроют регистрацию)
- Flathub и AppImage на других дистрибутивах
- Больше языков

## Как помочь

Ошибки и идеи — в [Issues](https://github.com/whooduck-crypto/whoohub/issues). Код, переводы и упаковка —
см. [CONTRIBUTING.md](CONTRIBUTING.md). Разработка и перевод описаны в разделах
[Development](README.md#development) и [Translating](README.md#translating) английского README.

## Лицензия

[GPL-3.0-or-later](LICENSE).
