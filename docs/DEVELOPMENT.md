# Разработка, тестирование и сборка

## Требования

- macOS Tahoe 26.2+ с Xcode 26.5 или совместимым Xcode 26.6;
- iOS SDK 26.5;
- для локальной UI-автоматизации: Maestro CLI и Java 17+;
- для физической установки: Windows 11 или macOS, Sideloadly, кабель/Trust и
  бесплатный Apple-аккаунт.

Windows не может выполнить Xcode-сборку. MacBook Air 2017 с Monterey не может
запустить Xcode 26.5, поэтому проверяемые сборки выполняются на современном macOS
runner. Apple credentials в CI не нужны и не допускаются.

## Диагностика Xcode

```bash
xcodebuild -version
xcrun --sdk iphoneos --show-sdk-version
xcodebuild -project Rabotyaga.xcodeproj -scheme Rabotyaga -list
```

Ожидается Xcode 26.5/26.6 и SDK 26.5. Deployment target проекта остаётся iOS 15.0.

## Сборка для симулятора

```bash
xcodebuild \
  -project Rabotyaga.xcodeproj \
  -scheme Rabotyaga \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 15 Pro' \
  -derivedDataPath build/DerivedData \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Если в установленном Xcode нет simulator runtime или указанной модели, выбрать
доступный iPhone через `xcrun simctl list devices available`. Отсутствие модели не
исправлять подменой production target.

## Maestro smoke test

Maestro работает с iOS Simulator, но пока не поддерживает физический iPhone.
После сборки и запуска выбранного simulator:

```bash
xcrun simctl install booted build/DerivedData/Build/Products/Debug-iphonesimulator/Rabotyaga.app
maestro test .maestro/smoke.yaml
```

Flow проверяет запуск, главный заголовок, кнопку, версию, результат нажатия,
закрытие и повторный запуск. Он не считается выполненным, пока команда реально не
завершилась успешно на iOS Simulator.

Для Maestro MCP после установки CLI:

```bash
codex mcp add maestro -- maestro mcp
codex mcp list
```

Codex Desktop использует тот же `~/.codex/config.toml`; после настройки нужно
перезапустить приложение. Не добавлять MCP-конфигурацию, пока команда `maestro mcp`
не запускается локально.

## Ручная UI-проверка

На iPhone 15 Pro simulator и компактном iPhone проверить:

- portrait и landscape, safe areas и отсутствие обрезки;
- все accessibility Dynamic Type sizes;
- VoiceOver: заголовок, кнопка, hint, сообщение результата и версия;
- Reduce Motion, Increase Contrast и Bold Text;
- отсутствие ошибок в Xcode console;
- повторный запуск после остановки приложения.

Навигация сейчас отсутствует по дизайну, поэтому тестировать переходы нечего. При
добавлении второго экрана smoke flow должен получить отдельные шаги перехода и
возврата.

## Неподписанный IPA

Локально на совместимом Mac или в CI:

```bash
bash scripts/build_unsigned_ipa.sh
unzip -l build/Rabotyaga-unsigned.ipa
```

Ожидаемый артефакт: `build/Rabotyaga-unsigned.ipa` с
`Payload/Rabotyaga.app`. Скрипт отключает Xcode code signing. Не добавлять к нему
сертификаты или provisioning profiles.

### GitHub Actions

`.github/workflows/build-unsigned-ipa.yml` использует стандартный `macos-26`
runner и `/Applications/Xcode_26.5.app`. На публичном репозитории стандартный
runner бесплатен; workflow сохраняет IPA на 7 дней.

### Codemagic

`codemagic.yaml` использует бесплатный personal `mac_mini_m2`, Xcode 26.5 и тот
же build script. Конфигурация запускается вручную. Бесплатный personal account
даёт 500 macOS M2 минут в месяц; не включать billing и не использовать M4.

## Установка через Sideloadly

1. Скачать `Rabotyaga-unsigned.ipa` на локальный компьютер.
2. Подключить разблокированный iPhone, подтвердить Trust и включить Developer Mode.
3. Перетащить IPA в Sideloadly и выполнить Apple ID Sideload.
4. Apple ID и пароль вводить только локально в Sideloadly, не в GitHub/Codemagic.
5. После установки доверить профиль в Settings → General → VPN & Device Management.
6. Проверить иконку, кнопку, закрытие и повторный запуск без подключения к Mac.

Бесплатная подпись действует семь дней и ограничена тремя установленными
приложениями. Использовать одинаковые Apple ID и bundle ID для обновления; включить
автоматический refresh либо повторно подписывать IPA до истечения срока.
