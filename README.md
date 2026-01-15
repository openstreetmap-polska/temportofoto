# temportofoto
Aplikacja, która pobiera wskazany arkusz ortofotomapy z geoportalu i udostępnia go w postaci kafli rastrowych XYZ, które można podpiąć do edytorów OSM (iD, JOSM).

Wersja wczesna. Możliwe błędy i słabe działanie.

## Uruchamianie usługi samemu
Do uruchomienia wymaga zmiennych środowiskowych lub pliku `.env`.
Przykład zawartości:
```
temportofoto_db_connection_string=sqlite+aiosqlite:////mnt/nvme/git/temportofoto/testing/test.db
temportofoto_data_dir=/mnt/nvme/git/temportofoto/testing
temportofoto_base_url=http://127.0.0.1:8000
```

### uv
Zależności można zainstalować używając [uv](https://docs.astral.sh/uv/) komendą:
```bash
uv sync --freeze
```

Po tym można uruchomić serwer lokalnie używając komendy:
```bash
uv run fastapi run app/main.py
```

### Docker
Można skorzystać też z Dockerfile i zbudować kontener.
