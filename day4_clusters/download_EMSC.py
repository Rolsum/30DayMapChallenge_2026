import os
import json
import time
import glob
import requests
from datetime import datetime

# --- НАСТРОЙКИ ---
START_YEAR = 1998
END_YEAR = datetime.now().year  # 2026

# Границы Кавказа (Bounding Box)
BBOX = {
    "minlat": 38.0,
    "maxlat": 45.5,
    "minlon": 37.0,
    "maxlon": 51.0,
}

# Минимальная магнитуда (None — качать вообще все события, либо укажите, например, 2.0)
MIN_MAGNITUDE = None

CHUNK_DIR = "emsc_chunks"
OUTPUT_FILE = "caucasus_emsc_full_archive.geojson"
API_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"
LIMIT = 2000  # Безопасный размер одной пачки для EMSC


def fetch_year_data(year: int) -> list:
    """Скачивает все события за указанный год с учетом пагинации (offset)."""
    start_time = f"{year}-01-01T00:00:00"
    end_time = f"{year + 1}-01-01T00:00:00"

    year_features = []
    offset = 1  # В стандарте FDSN индексация offset начинается с 1

    while True:
        params = {
            **BBOX,
            "starttime": start_time,
            "endtime": end_time,
            "format": "json",  # Возвращает GeoJSON FeatureCollection
            "limit": LIMIT,
            "offset": offset,
        }
        if MIN_MAGNITUDE is not None:
            params["minmag"] = MIN_MAGNITUDE

        # Попытки запроса на случай временной перегрузки сервера
        for attempt in range(3):
            try:
                response = requests.get(API_URL, params=params, timeout=30)
                break
            except requests.RequestException as e:
                print(f"  [!] Ошибка сети ({e}), повтор {attempt + 1}/3...")
                time.sleep(3)
        else:
            print(f"  [X] Не удалось получить данные за {year} год (offset={offset}).")
            break

        # Код 204 или 404 у EMSC означает, что событий в этом диапазоне больше нет
        if response.status_code in (204, 404):
            break

        if response.status_code != 200:
            print(f"  [!] Неожиданный код ответа {response.status_code} за {year} год.")
            break

        data = response.json()
        features = data.get("features", [])

        if not features:
            break

        year_features.extend(features)
        print(f"  -> Загружено {len(features)} событий (всего за {year}: {len(year_features)})")

        # Если пришло меньше событий, чем лимит, значит мы дошли до конца года
        if len(features) < LIMIT:
            break

        offset += LIMIT
        time.sleep(1)  # Небольшая пауза, чтобы не блокировал сервер

    return year_features


def download_all_chunks():
    """Скачивает данные по годам в отдельные файлы .geojson."""
    os.makedirs(CHUNK_DIR, exist_ok=True)

    for year in range(START_YEAR, END_YEAR + 1):
        chunk_path = os.path.join(CHUNK_DIR, f"caucasus_{year}.geojson")

        # Пропускаем уже скачанные годы (кроме текущего, так как он еще пополняется)
        if os.path.exists(chunk_path) and year < END_YEAR:
            print(f"[✓] Файл за {year} год уже существует, пропускаем...")
            continue

        print(f"Скачивание данных за {year} год...")
        features = fetch_year_data(year)

        geojson_chunk = {
            "type": "FeatureCollection",
            "metadata": {
                "region": "Caucasus",
                "source": "EMSC (SeismicPortal)",
                "year": year,
                "count": len(features),
            },
            "features": features,
        }

        with open(chunk_path, "w", encoding="utf-8") as f:
            json.dump(geojson_chunk, f, ensure_ascii=False)

        print(f"[+] Сохранен {chunk_path} ({len(features)} событий)\n")
        time.sleep(1)


def merge_geojson_files():
    """Объединяет все годовые .geojson файлы в один без дубликатов."""
    print("Объединение всех файлов в единый GeoJSON...")
    chunk_files = sorted(glob.glob(os.path.join(CHUNK_DIR, "caucasus_*.geojson")))

    unique_features = {}

    for file_path in chunk_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for feature in data.get("features", []):
                # Уникальный ID события в EMSC хранится в feature['id'] или properties['unid']
                event_id = feature.get("id") or feature.get("properties", {}).get("unid")
                if event_id:
                    unique_features[event_id] = feature

    # Сортируем события по времени от старых к новым
    sorted_features = sorted(
        unique_features.values(),
        key=lambda x: x.get("properties", {}).get("time", ""),
    )

    final_geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "EMSC Caucasus Full Earthquake Archive",
            "period": f"{START_YEAR}-{END_YEAR}",
            "bbox": BBOX,
            "total_events": len(sorted_features),
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
        "features": sorted_features,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_geojson, f, ensure_ascii=False)

    print(f"\nГотово! Итоговый файл: {OUTPUT_FILE}")
    print(f"Всего уникальных землетрясений в архиве: {len(sorted_features)}")


if __name__ == "__main__":
    download_all_chunks()
    merge_geojson_files()