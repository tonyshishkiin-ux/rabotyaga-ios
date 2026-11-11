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

