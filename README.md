# Работяга iOS 1.2

Нативный SwiftUI-клиент «Работяги» для бесплатной установки на физический
iPhone. Версия 1.2 добавляет настоящий текстовый чат с существующим Hermes Agent
через отдельный защищённый Windows-шлюз. Проект не содержит токенов, Apple ID,
сертификатов, персональных данных Hermes или сторонних iOS-зависимостей.

## Интерфейс

- «Чат» — реальные сообщения, ответы Hermes, статусы длительных задач,
  восстановление истории и точечные подтверждения действий;
- «Шабашка» — демонстрационные карточки заказов и решения свайпами/кнопками;
- «Задачи» — локально сохранённые интересные и отложенные карточки;
- «Настройки» — безопасное одноразовое спаривание, статус подключения, отзыв
  доступа устройства и версия приложения;
- принудительная тёмная тема и версия из `CFBundleShortVersionString`.

## Локальная сборка

```bash
xcodebuild \
  -project Rabotyaga.xcodeproj \
  -scheme Rabotyaga \
  -configuration Release \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

## GitHub Actions

Workflow `.github/workflows/build-unsigned-ipa.yml` собирает неподписанный IPA
на стандартном `macos-26` runner с Xcode 26.5. Apple ID и signing secrets в CI
не передаются. Полученный IPA предназначен для локальной подписи владельцем.

## Документация

- [Дизайн-система](docs/DESIGN_SYSTEM.md) — HIG, визуальные токены,
  accessibility и будущая навигация.
- [Разработка и тестирование](docs/DEVELOPMENT.md) — Xcode, Maestro, CI,
  unsigned IPA и установка через Sideloadly.
- [Интеграция Hermes](docs/HERMES_INTEGRATION.md) — подтверждённый протокол,
  модель угроз, gateway API, Tailscale и подключение iPhone.
- [Правила для Codex](AGENTS.md) — стек, безопасность, Git и обязательные
  проверки для следующих задач.

Gateway-тесты выполняются в GitHub Actions перед Xcode-сборкой. Физический тест
чата 1.2 требует включённого Tailscale на iPhone, отдельного запуска локального
шлюза и установки unsigned IPA через Sideloadly.

