<p align="center">
  <img src="data/icons/io.github.whooduck_crypto.Whoohub.svg" width="128" alt="значок whoohub">
</p>

<h1 align="center">whoohub</h1>

<p align="center">
  Один магазин приложений для систем на базе Arch: официальные репозитории, Flathub, AUR и AppImage в одном месте.
  <br>
  <a href="README.md">Read in English</a>
</p>

<p align="center">
  <img src="docs/screenshot.png" width="800" alt="whoohub: вкладка «Игры»">
</p>

## Зачем

В Arch программы живут в четырёх местах, и у каждого свой инструмент: `pacman`, `flatpak`, помощник для
AUR и AppImage, которые скачивают вручную. whoohub ищет сразу везде и показывает **каждую программу один
раз** — с выбором, откуда её поставить, и понятным объяснением, чем источники отличаются.

## Возможности

- **Как магазин в телефоне.** Главная с баннером «Программа дня» и полками (Популярное, Игры, Для
  творчества, Для работы, Интернет и общение, Полезные утилиты), вкладки «Игры» и «Программы», «Мои
  приложения» и поиск всегда сверху.
- **Одна кнопка у каждой программы.** «Установить» / «Открыть» прямо в любом списке — без захода на страницу.
- **Одна страница на программу.** Firefox из репозиториев и с Flathub — это одна программа; откуда её
  поставить, спокойно выбирается внизу страницы, с объяснением простыми словами.
- **Репозитории (pacman)** — установка через графическое окно пароля polkit, без терминала.
- **Flathub** — установка в твой профиль, без пароля.
- **AUR** — поиск онлайн; перед сборкой whoohub показывает PKGBUILD и предупреждает, ставит недостающие
  зависимости из репозиториев и собирает пакет через `makepkg`.
- **AppImage** — каталог AppImageHub; whoohub скачивает последний стабильный выпуск с GitHub автора в
  `~/Applications` и добавляет ярлык в меню.
- **Проверка обновлений** — раз в сутки whoohub спрашивает у GitHub последний выпуск и предлагает обновиться прямо из программы: установленный пакетом — через `pacman -U`, установленный через `make install` — переустановкой исходников выпуска в ту же папку; всегда после сверки контрольной суммы от GitHub. Отключается в меню.
- Светлая и тёмная тема по настройке системы (libadwaita). Английский и русский; другие языки — welcome.

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

Сеть: кроме каталогов и файлов устанавливаемых программ, whoohub раз в сутки делает один запрос к API GitHub за своим последним выпуском (никаких данных о тебе; отключается пунктом «Проверять обновления автоматически»).

О доверии: пакеты AUR и AppImage публикуют их авторы, а не Arch Linux или Flathub. whoohub пишет об этом
на каждой такой странице и показывает скрипт сборки AUR до сборки.

## Разработка и перевод

См. разделы [Development](README.md#development) и [Translating](README.md#translating) в английском README.

## Лицензия

[GPL-3.0-or-later](LICENSE).
