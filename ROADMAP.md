# HeadTracker — Дорожная карта прототипа

## Цель
Простой рабочий прототип для Windows: веб-камера → трекинг головы → FreeTrack 2.0 → игра.

## Стек

| Компонент | Технология | Лицензия |
|-----------|-----------|----------|
| Язык | Python 3.11+ | — |
| Камера | OpenCV VideoCapture | Apache 2.0 |
| Трекинг | MediaPipe FaceMesh + cv2.solvePnP() | Apache 2.0 |
| Фильтр | Заглушка (One Euro Filter — каркас) | — |
| GUI | PySide6 | LGPL v3 |
| FreeTrack output | Windows shared memory через ctypes | — |
| Конфиг | JSON | — |

## Архитектура (pipeline)

```
Webcam → Camera Capture → MediaPipe FaceMesh (478 landmarks)
→ cv2.solvePnP() → Pose(yaw, pitch, roll, x, y, z)
→ Filter (stub) → Mapping (sensitivity, deadzone, inversion)
→ FreeTrack 2.0 shared memory → Game
```

## Структура файлов

```
HeadTracker/
├── main.py                      # Точка входа
├── pyproject.toml               # Зависимости
├── ROADMAP.md                   # Этот файл
├── THIRD_PARTY_LICENSES         # Лицензии зависимостей
│
├── camera.py                    # Захват с веб-камеры (OpenCV)
├── tracker.py                   # MediaPipe FaceMesh → PnP → yaw/pitch/roll/x/y/z
├── filter.py                    # Заглушка фильтра (One Euro каркас)
├── freetrack.py                 # FreeTrack 2.0 shared memory output (ctypes)
├── config.py                    # Загрузка/сохранение JSON конфига
│
├── ui/
│   └── main_window.py           # Главное окно: превью камеры + настройки
│
└── profiles/
    ├── default.json
    └── assetto_corsa.json
```

## Модули

### camera.py — Захват кадров
- Enumerate камеры (индекс, разрешение, FPS)
- start(index, width, height, fps) → открывает VideoCapture
- get_frame() → numpy array (BGR) + timestamp
- stop() → освобождает камеру
- Mirror mode (отзеркаливание)

### tracker.py — Определение положения головы
- MediaPipe FaceMesh: 478 3D-landmarks
- Ключевые точки для PnP: нос(1), подбородок(152), левый глаз(33), правый глаз(263), левый рот(61), правый рот(291)
- cv2.solvePnP() → rvec, tvec
- cv2.Rodrigues(rvec) → rotation matrix → Euler angles
- Face loss: confidence=0, удержание последней валидной позы
- Возврат: Pose(yaw, pitch, roll, x, y, z, confidence, timestamp)

### filter.py — Заглушка фильтра
- Каркас One Euro Filter (min_cutoff, beta)
- Pass-through (без фильтрации на старте)
- Интерфейс: filter_value(value, timestamp) → filtered_value

### freetrack.py — FreeTrack 2.0 output
- Windows shared memory: CreateFileMappingA("FT_SharedMem"), MapViewOfFile()
- Мьютекс: CreateMutexA("FT_Mutext")
- Структура FTHeap → FTData
- Конвертация: градусы → радианы для rotation, мм для translation
- Регистрация в реестре (HKCU\Software\Freetrack\FreetrackClient\Path)
- start() / send_pose(pose) / stop()

### config.py — Конфигурация
- Загрузка/сохранение JSON
- Структура профиля:
```json
{
  "name": "Profile Name",
  "camera_index": 0,
  "camera_width": 640,
  "camera_height": 480,
  "camera_fps": 30,
  "mirror": true,
  "axes": {
    "yaw":   { "enabled": true, "sensitivity": 6.0, "deadzone": 2.0, "inverted": false },
    "pitch": { "enabled": true, "sensitivity": 6.0, "deadzone": 2.0, "inverted": false },
    "roll":  { "enabled": true, "sensitivity": 6.0, "deadzone": 2.0, "inverted": false },
    "x":     { "enabled": true, "sensitivity": 1.0, "deadzone": 1.0, "inverted": false },
    "y":     { "enabled": true, "sensitivity": 1.0, "deadzone": 1.0, "inverted": false },
    "z":     { "enabled": true, "sensitivity": 1.0, "deadzone": 1.0, "inverted": false }
  },
  "output": { "protocol": "freetrack" },
  "hotkeys": { "center": "F12", "reset": "F11" }
}
```

### ui/main_window.py — Интерфейс
- PySide6 QMainWindow
- Левая часть: превью камеры с overlay landmarks
- Правая часть: текущие yaw/pitch/roll/x/y/z + confidence + FPS
- Кнопки: Start/Stop, Center, Reset
- Настройки: камера, разрешение, mirror, оси (sensitivity, deadzone, inversion)
- Выбор профиля

### profiles/*.json — Готовые профили
- default.json — универсальные настройки
- assetto_corsa.json — настроенные оси для AC

## Горячие клавиши
- F12 — Center (установить текущую позу как центр)
- F11 — Reset (сбросить центр)

## Порядок реализации

| # | Файл | Описание |
|---|------|----------|
| 1 | pyproject.toml | Зависимости |
| 2 | camera.py | Захват кадров |
| 3 | tracker.py | MediaPipe + PnP |
| 4 | filter.py | Заглушка фильтра |
| 5 | freetrack.py | FreeTrack 2.0 output |
| 6 | config.py | JSON конфиг |
| 7 | profiles/*.json | Профили |
| 8 | ui/main_window.py | GUI |
| 9 | main.py | Точка входа |
| 10 | THIRD_PARTY_LICENSES | Лицензии |

## Критерий успеха
Пользователь запускает программу → выбирает камеру → нажимает Start →
видит превью с landmarks → запускает Assetto Corsa →
головой осматривает кокпит (зеркала, боковые направления).
