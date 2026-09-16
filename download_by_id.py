"""
Скачивание файла ассета Roblox по ID через Open Cloud Asset Delivery API.

Использование:
    pip install requests
    python download_by_id.py <asset_id> [имя_выходного_файла]

Если файла api.key нет — скрипт спросит ключ и сохранит его в api.key
(в той же папке, где лежит этот скрипт) для последующих запусков.

Ключ — это Open Cloud API Key (создаётся на
https://create.roblox.com/dashboard/credentials, нужно право доступа
"Assets" со scope asset:read). Ключ передаётся в заголовке x-api-key.

ВАЖНО: Open Cloud позволяет читать только те ассеты, к которым у ключа
есть доступ (собственные ассеты пользователя/группы, на которого
выпущен ключ). Скачать произвольный чужой приватный ассет по ID
таким способом не получится — это не обход прав доступа, а обращение
к вашим собственным ассетам через официальный API.
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
    key = input("Введите Open Cloud API-ключ (x-api-key): ").strip()
    KEY_FILE.write_text(key, encoding="utf-8")
    print(f"Ключ сохранён в {KEY_FILE}")
    return key


def build_session(key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    if key:
        session.headers["x-api-key"] = key
    return session


def get_asset_metadata(session: requests.Session, asset_id: str) -> dict:
    """Запрашивает метаданные ассета (включая creator) через Open Cloud Assets API."""
    api_url = f"https://apis.roblox.com/assets/v1/assets/{asset_id}"
    r = session.get(api_url, timeout=30)
    if not r.ok:
        raise RuntimeError(
            f"Не удалось получить метаданные ассета {asset_id}: HTTP {r.status_code}\n{r.text[:500]}"
        )
    return r.json()


def try_public_legacy_download(session: requests.Session, asset_id: str) -> bytes | None:
    """
    Пытается скачать файл через публичный (без x-api-key) legacy Asset Delivery API v2.
    Для многих типов ассетов (например, Image/Decal) содержимое отдаётся публично,
    т.к. оно должно рендериться в любой игре у любого игрока.
    Возвращает bytes или None, если публично не отдаётся.
    """
    plain_session = requests.Session()
    plain_session.headers.update(HEADERS)

    api_url = f"https://assetdelivery.roblox.com/v2/assetId/{asset_id}"
    r = plain_session.get(api_url, timeout=30)
    print(f"  [публичный v2] HTTP {r.status_code}: {r.text[:300]}")
    if not r.ok:
        return None

    data = r.json()
    locations = data.get("locations") or []
    if not locations:
        print("  [публичный v2] в ответе нет locations")
        return None

    location = locations[0]
    file_url = location.get("location")
    if not file_url:
        print(f"  [публичный v2] location без ссылки: {location}")
        return None

    file_r = plain_session.get(file_url, timeout=60)
    print(f"  [публичный v2, скачивание файла] HTTP {file_r.status_code}")
    if not file_r.ok:
        return None
    return file_r.content


def resolve_download_url(session: requests.Session, asset_id: str) -> str:
    """Получает прямую ссылку на файл ассета через Open Cloud Asset Delivery API."""
    api_url = f"https://apis.roblox.com/asset-delivery-api/v1/assetId/{asset_id}"
    r = session.get(api_url, allow_redirects=False, timeout=30)

    if r.status_code in (301, 302, 303, 307, 308) and "Location" in r.headers:
        return r.headers["Location"]

    if r.status_code == 200:
        # Ответ может быть либо сразу файлом, либо JSON с полем "location".
        content_type = r.headers.get("Content-Type", "")
        if "application/json" in content_type:
            data = r.json()
            location = data.get("location")
            if location:
                return location
            raise RuntimeError(f"В ответе нет ссылки на файл: {data}")
        return api_url  # ответ уже содержит файл, скачивать можно по этому же URL

    raise RuntimeError(
        f"Не удалось получить ссылку на ассет {asset_id}: HTTP {r.status_code}\n{r.text[:500]}"
    )


def download_file(session: requests.Session, url: str, out_path: Path) -> None:
    r = session.get(url, timeout=60, allow_redirects=True)
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

    print(f"Пробую публичный (без ключа) способ для id={asset_id}...")
    key = load_or_ask_key()
    session = build_session(key)

    content = try_public_legacy_download(session, asset_id)
    if content is not None:
        out_path.write_bytes(content)
        print("Готово (публичный способ):", out_path.resolve())
        return

    print("Публичный способ не сработал, пробую Open Cloud API с ключом...")

    try:
        meta = get_asset_metadata(session, asset_id)
        creator = meta.get("creationContext", {}).get("creator", {})
        print(f"Метаданные ассета: displayName={meta.get('displayName')!r}, "
              f"assetType={meta.get('assetType')}, creator={creator}")
    except RuntimeError as e:
        print(f"(Не удалось получить метаданные ассета: {e})")

    url = resolve_download_url(session, asset_id)

    print(f"Скачиваю файл в {out_path} ...")
    download_file(session, url, out_path)

    print("Готово:", out_path.resolve())


if __name__ == "__main__":
    main()
