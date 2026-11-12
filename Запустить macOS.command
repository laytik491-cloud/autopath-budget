#!/bin/zsh
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
    printf '%s\n' 'Установите Python 3.11 или новее с сайта https://www.python.org/downloads/'
    printf '%s\n' 'Затем снова откройте этот файл.'
    read -r '?Нажмите Enter для закрытия'
    exit 1
fi
python3 launch.py "$@"
