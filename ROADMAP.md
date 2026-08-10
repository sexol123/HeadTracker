# HeadTracker — Дорожная карта

## Статус

Рабочее приложение для трекинга головы (Windows/Linux/macOS): веб-камера →
трекинг → FreeTrack 2.0 / UDP / Mouse → игра. Полный список возможностей,
установка и использование — в `README.md`. Остатки «прототипа» (заглушки,
устаревшие описания) устранены; этот файл описывает актуальную архитектуру и
направление развития.

## Стек

| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.11+ |
| Камера | OpenCV VideoCapture (USB, RTSP/HTTP) + WebSocket (телефон) |
| Трекинг | MediaPipe FaceLandmarker (478 лендмарков, до нескольких лиц) + cv2.solvePnP |
| Фильтр | AdaptiveExponentialFilter (EMA, быстрый подъём / медленный спад) |
| GUI | PySide6 |
| Output | FreeTrack 2.0 shared memory, UDP, Mouse (velocity/absolute, pynput) |
| Конфиг | JSON-профили + `settings.json` (атомарная запись) |
| Тесты | автономные скрипты `tests/test_*.py`, `run_tests.bat` (offscreen UI) |

## Архитектура (pipeline)

```
Camera (local/RTSP/WebSocket) → HeadTracker.process_frame
→ выбор лица (несколько в кадре, ID-стабильность по центру)
→ cv2.solvePnP → Pose(yaw, pitch, roll, x, y, z, confidence)
→ CameraCalibration (адаптация монтажа + центр)
→ AdaptiveExponentialFilter (smoothing)
→ Mapping (deadzone → нелинейная кривая → ×sensitivity → инверсия)
→ Output (FreeTrack / UDP / Mouse) → Game
```

Фоновый поток: `TrackingWorker` (QThread) — камера, трекинг, output, hotkey-
слушатель; UI-поток получает кадры/позы/статистику через сигналы. Все
live-обновления настроек — под `QMutex`.

## Структура файлов (актуальная)

```
HeadTracker/
├── main.py                  # Точка входа: лог, splash, CLI (--profile, --autostart)
├── camera.py                # Камеры: local (VideoCapture), IP (RTSP/HTTP), WebSocket;
│                            #   stall-детект (5 с), stats (FPS/bandwidth/dropped)
├── tracker.py               # FaceLandmarker → multi-face → PnP → Pose; hold/блендинг
├── worker.py                # TrackingWorker: поток, рестарт камеры, кривые, hotkey-комбо
├── filter.py                # AdaptiveExponentialFilter
├── cam_calib.py             # CameraCalibration: компенсация монтажа, центр, FOV
├── pose.py                  # Pose (dataclass)
├── config.py                # Profile (оси, кривые, center_pose), AppSettings,
│                            #   save/load, атомарная запись
├── freetrack.py             # FreeTrack 2.0 shared memory (ctypes)
├── udp_output.py            # UDP-выход
├── mouse_output.py          # Mouse-выход (velocity/absolute, hotkey)
├── i18n.py                  # en/ru/uk/de
├── crashlog.py              # Дампы падений в logs/
├── ui/
│   ├── main_window.py       # Главное окно (вкладки Camera/Axes/Output/Log/About)
│   ├── axes_helper_dialog.py# Визуальная настройка осей: кривая + живой тест
│   ├── cam_setup_dialog.py  # Визуальная адаптация камеры (вид сверху/сбоку)
│   └── stats_graph.py       # График FPS/времени кадра/задержки с маркерами
├── tests/                   # 24 автономных сьюта (юнит, PnP, UI, рендер по пикселям)
├── profiles/                # default.json + пресеты игр
└── models/face_landmarker.task  # модель MediaPipe (setup.bat)
```

## Куда дальше (идеи, не обязательства)

- **Импорт/экспорт профилей (JSON)** — шаринг настроек, бэкап перед экспериментами (отложено по решению пользователя).
- **Переключение лица кликом по превью** — сейчас выбор комбобоксом «Лицо 1/2/…», клик по рамке был бы удобнее.
- **Фильтр One Euro / предсказание** — для игр с инерцией smoother может не хватать; перспективно, но требует аккуратного подбора параметров и тестов на латентность.
- **Профили под hotkey** — привязать профиль к запущенной игре/горячей клавише.
- **Низкий уровень света** — авто-порог CLAHE вместо фиксированного.
- **Телеметрия** — экспорт логов трекинга (CSV) для анализа качества.

## Критерий успеха (актуальный)

Пользователь запускает программу → выбирает камеру → нажимает Start → видит
превью с лендмарками → при необходимости настраивает оси/адаптацию/кривые в
хелперах → запускает игру (FreeTrack/UDP) → голова отслеживается стабильно,
без перескоков между людьми в кадре, с автовосстановлением после сна.
Правки профилей/настроек не теряются даже при аварийном завершении.
