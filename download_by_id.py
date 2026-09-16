"""
Скачивание файла ассета Roblox по ID через Asset Delivery API.

Использование:
    pip install requests
    python download_by_id.py <asset_id> [имя_выходного_файла]

Если файла api.key нет — скрипт спросит ключ и сохранит его в api.key
(в той же папке, где лежит этот скрипт) для последующих запусков.

Ключ — это .ROBLOSECURITY cookie или API-ключ Open Cloud (Roblox),
в зависимости от того, какой эндпоинт вы используете. По умолчанию
используется публичный Asset Delivery API (assetdelivery.roblox.com),
для которого ключ обычно не обязателен, но некоторые ассеты требуют
авторизации — тогда ключ используется как cookie .ROBLOSECURITY.
"""

import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
KEY_FILE = SCRIPT_DIR / "api.key"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, application/octet-stream, */*",
}


def load_or_ask_key() -> str:
    """Читает ключ из api.key рядом со скриптом; если файла нет — спрашивает и сохраняет."""
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    print("Файл api.key не найден или пуст.")
    key = input("Введите API-ключ / .ROBLOSECURITY (можно оставить пустым и нажать Enter): ").strip()
    KEY_FILE.write_text(key, encoding="utf-8")
    print(f"Ключ сохранён в {KEY_FILE}")
    return key


def build_session(key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    if key:
        # Используем ключ как .ROBLOSECURITY cookie для запросов, требующих авторизации.
        session.cookies.set(".ROBLOSECURITY", key, domain=".roblox.com")
    return session


def resolve_download_url(session: requests.Session, asset_id: str) -> str:
    """Получает прямую ссылку на файл ассета через Asset Delivery API v1."""
    api_url = f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}"
    r = session.get(api_url, allow_redirects=False, timeout=30)

    # Иногда API сразу отдаёт файл, иногда — редиректит на CDN.
    if r.status_code in (301, 302, 303, 307, 308) and "Location" in r.headers:
        return r.headers["Location"]
    if r.status_code == 200:
        return api_url  # можно скачивать прямо по этому URL
    raise RuntimeError(
        f"Не удалось получить ссылку на ассет {asset_id}: HTTP {r.status_code}\n{r.text[:500]}"
    )


def download_file(session: requests.Session, url: str, out_path: Path) -> None:
    r = session.get(url, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Ошибка скачивания {url}: HTTP {r.status_code}\n{r.text[:500]}")
    out_path.write_bytes(r.content)


def main():
    if len(sys.argv) < 2:
        print("Использование: python download_by_id.py <asset_id> [имя_выходного_файла]")
        sys.exit(1)

    asset_id = sys.argv[1]
    out_name = sys.argv[2] if len(sys.argv) > 2 else f"{asset_id}.rbxm"
    out_path = Path.cwd() / out_name

    key = load_or_ask_key()
    session = build_session(key)

    print(f"Запрашиваю ассет id={asset_id}...")
    url = resolve_download_url(session, asset_id)

    print(f"Скачиваю файл в {out_path} ...")
    download_file(session, url, out_path)

    print("Готово:", out_path.resolve())


if __name__ == "__main__":
    main()
