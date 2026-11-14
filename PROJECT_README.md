# Карта и предложение схемы БД для командного приложения

Границы работ: серверный разработчик — REST API на **Fastify**, Docker и
развёртывание; Павел — планировщик; наша часть — **`web/` и схема БД**.
Официальный внешний контракт — неизменённый `api_spec.yaml`.

| Каталог | Назначение |
|---|---|
| `web/` | Карта, маршруты, Гант, наряды, предупреждения; без серверных зависимостей |
| `contracts/ui-api.yaml` | Предложение трёх GET `/api/ui/...` для реализации в Fastify |
| `contracts/examples/` | JSON-примеры запросов и ответов, включая пустой день и ошибки |
| `db/proposals/` | SQL схемы для согласования; целевая PostgreSQL 16 |
| `data/` | Синтетический набор и выбранные реальные адреса; не данные организаторов |
| `demo/` | Изолированный прежний прототип FastAPI/OR-Tools, не итоговое приложение |

Начать интеграцию: [docs/ui_api.md](docs/ui_api.md) и [db/README.md](db/README.md).
Статусы согласования и последовательность — [docs/integration.md](docs/integration.md).

## Локально посмотреть карту

```powershell
.\demo\start.ps1
```

Используется только демонстрационный сервер и файловые данные, без подключения
к PostgreSQL. Подготовка окружения и запуск — [demo/README.md](demo/README.md).
Командный Fastify-сервер здесь не реализуется. Общие Compose, `.env.example`
и установщик не предлагаются к замене; демонстрационные варианты находятся в `demo/`.

## Проверки нашей части

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/dispatch-model.test.mjs
```

Дополнительные исторические проверки Python-прототипа запускаются явно:
`.\.venv\Scripts\python.exe -m pytest -c demo/pytest.ini demo/tests -q`.

Сырые OSM-выгрузки и кэши находятся вне версионируемого набора в `tmp/geodata-cache/`.
Источник, лицензия и получение заново — [docs/geodata_sources.md](docs/geodata_sources.md).
Для обычного запуска карты скачивать их заново не требуется.
