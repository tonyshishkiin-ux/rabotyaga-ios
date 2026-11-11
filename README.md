# Работяга iOS — этап 0

Минимальное SwiftUI-приложение для проверки бесплатной установки на физический
iPhone. Проект не содержит токенов, Apple ID, сертификатов, данных Hermes или
сторонних зависимостей.

## Экран

- название «Работяга»;
- принудительная тёмная тема;
- заголовок «Привет, начальник!»;
- кнопка «Проверить Работягу»;
- результат «Первое приложение работает»;
- версия приложения из `CFBundleShortVersionString`.

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
- [Правила для Codex](AGENTS.md) — стек, безопасность, Git и обязательные
  проверки для следующих задач.

Maestro smoke flow находится в `.maestro/smoke.yaml`. Он подготовлен для запуска
на iOS Simulator, но ещё не выполнялся: на текущем Windows-компьютере нет iOS
Simulator, а старый MacBook несовместим с Xcode 26.5.

