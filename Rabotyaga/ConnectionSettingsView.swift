import SwiftUI

struct ConnectionSettingsView: View {
    @ObservedObject var store: ChatStore

    @AppStorage(HermesGatewayClient.gatewayURLKey) private var gatewayURL = ""
    @State private var pairingCode = ""
    @State private var showingRevokeConfirmation = false

    var body: some View {
        NavigationView {
            List {
                Section("Подключение Hermes") {
                    Label(statusTitle, systemImage: statusIcon)
                        .foregroundColor(statusColor)
                    TextField("https://имя-устройства.tailnet.ts.net", text: $gatewayURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled(true)
                        .keyboardType(.URL)
                        .disabled(store.isConfigured)
                        .accessibilityLabel("Защищённый адрес шлюза")
                    if !store.isConfigured {
                        SecureField("Одноразовый код", text: $pairingCode)
                            .keyboardType(.numberPad)
                            .textContentType(.oneTimeCode)
                        Button {
                            Task {
                                if await store.pair(gatewayURL: gatewayURL, code: pairingCode) {
                                    pairingCode = ""
                                }
                            }
                        } label: {
                            if store.isRefreshing {
                                ProgressView().frame(maxWidth: .infinity)
                            } else {
                                Text("Подключить iPhone").frame(maxWidth: .infinity)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.accentColor)
                        .disabled(gatewayURL.isEmpty || pairingCode.count < 8 || store.isRefreshing)
                    } else {
                        Button("Проверить соединение") {
                            Task { await store.refresh() }
                        }
                        .disabled(store.isRefreshing)
                        Button("Отозвать доступ этого iPhone", role: .destructive) {
                            showingRevokeConfirmation = true
                        }
                    }
                    if let error = store.errorMessage {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote)
                            .foregroundColor(.orange)
                    }
                }

                Section("Безопасность") {
                    Text("Ключ устройства хранится только в Keychain. Каждый запрос подписывается и содержит одноразовый nonce. Hermes не публикуется в интернет.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                    Text("Для работы iPhone и Windows-компьютер должны быть подключены к одной сети Tailscale, а локальный шлюз — запущен.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }

                Section("О приложении") {
                    HStack {
                        Text("Версия")
                        Spacer()
                        Text(version)
                            .foregroundColor(.secondary)
                    }
                    Text("Шабашка остаётся в демонстрационном режиме. Отклики и другие внешние действия без отдельного подтверждения не отправляются.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
            }
            .navigationTitle("Настройки")
        }
        .navigationViewStyle(.stack)
        .alert("Отозвать доступ?", isPresented: $showingRevokeConfirmation) {
            Button("Отозвать", role: .destructive) {
                Task { _ = await store.revoke() }
            }
            Button("Отмена", role: .cancel) {}
        } message: {
            Text("Этот iPhone больше не сможет обращаться к шлюзу. История на Hermes не удаляется.")
        }
    }

    private var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.2"
    }

    private var statusTitle: String {
        guard store.isConfigured else { return "Hermes Agent: не подключён" }
        return store.connectionStatus == "ready" ? "Hermes Agent: на связи" : "Hermes Agent: \(store.connectionStatus)"
    }

    private var statusIcon: String {
        guard store.isConfigured else { return "wifi.slash" }
        return store.connectionStatus == "ready" ? "checkmark.shield.fill" : "arrow.triangle.2.circlepath"
    }

    private var statusColor: Color {
        guard store.isConfigured else { return .secondary }
        return store.connectionStatus == "ready" ? .green : .orange
    }
}
