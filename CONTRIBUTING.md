# Contributing · Участие

[English](#english) · [Русский](#русский)

## English

Bug reports, ideas and pull requests are welcome.

- **Bugs**: open an issue with the Blender version, the add-on version, the vehicle or part, what you did and what happened. A short `.jbeam` file that shows the problem helps the most.
- **Code**: the core (`jbeam_studio/core`) is plain Python and has no Blender in it; keep it that way, so it can be tested with `python -m pytest`. Blender code goes to `jbeam_studio/blender` and `jbeam_studio/ui`.
- **Tests**: add a test next to the change. Run `python -m pytest` for the core and `blender -b --factory-startup --python tests/blender/run.py` for Blender (on 4.5 and 5.2 when you can). Edits must keep the text of the files: only the values and rows that change may differ.
- **Interface**: every new text of the interface gets its Russian translation in `jbeam_studio/ui/translations.py`. Do not add common words that Blender translates itself, such as "Width" or "Type": an add-on's translation replaces Blender's everywhere.
- **Colours**: the defaults follow the game's debug view (`lua/vehicle/bdebugImpl.lua`).
- **Screenshots**: `scripts/screenshots.py` takes the pictures of the README from the ETK 800 of the game.

## Русский

Сообщения об ошибках, идеи и pull request'ы приветствуются.

- **Ошибки**: создайте issue с версией Blender, версией аддона, машиной или частью, тем, что вы делали и что произошло. Больше всего помогает короткий `.jbeam`-файл, на котором видна проблема.
- **Код**: ядро (`jbeam_studio/core`) — чистый Python без Blender; пусть так и остаётся, чтобы его можно было проверять через `python -m pytest`. Код для Blender — в `jbeam_studio/blender` и `jbeam_studio/ui`.
- **Тесты**: добавляйте тест рядом с изменением. Запускайте `python -m pytest` для ядра и `blender -b --factory-startup --python tests/blender/run.py` для Blender (по возможности на 4.5 и 5.2). Правки должны сохранять текст файлов: меняться могут только изменённые значения и строки.
- **Интерфейс**: у каждого нового текста интерфейса должен быть русский перевод в `jbeam_studio/ui/translations.py`. Не добавляйте общие слова, которые Blender переводит сам, вроде «Width» или «Type»: перевод аддона заменяет перевод Blender везде.
- **Цвета**: значения по умолчанию следуют отладочному режиму игры (`lua/vehicle/bdebugImpl.lua`).
- **Скриншоты**: `scripts/screenshots.py` снимает картинки для README с ETK 800 из игры.
