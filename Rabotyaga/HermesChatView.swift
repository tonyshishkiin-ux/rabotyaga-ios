import SwiftUI
import UIKit

struct HermesChatView: View {
    @ObservedObject var store: ChatStore
    let openSettings: () -> Void

    @State private var message = ""
    @FocusState private var composerFocused: Bool

    var body: some View {
        NavigationView {
            Group {
                if !store.isConfigured {
                    disconnectedView
                } else {
                    chatView
                }
            }
            .navigationTitle("Работяга")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    connectionLabel
                }
            }
        }
        .navigationViewStyle(.stack)
        .task { await store.refresh() }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.willEnterForegroundNotification)) { _ in
            Task { await store.refresh() }
        }
    }

    private var disconnectedView: some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: "bolt.fill")
                .font(.system(size: 44, weight: .bold))
                .foregroundColor(.accentColor)
                .accessibilityHidden(true)
            Text("Привет, начальник!")
                .font(.largeTitle.bold())
                .multilineTextAlignment(.center)
            Text("Подключите защищённый шлюз, чтобы получать настоящие ответы Hermes Agent.")
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
            Button("Настроить подключение", action: openSettings)
                .buttonStyle(.borderedProminent)
                .tint(.accentColor)
            Spacer()
        }
        .padding(24)
    }

    private var chatView: some View {
        VStack(spacing: 0) {
            if let error = store.errorMessage {
                errorBanner(error)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        if store.messages.isEmpty {
                            emptyChat
                        }
                        ForEach(store.messages) { item in
                            messageBubble(item)
                                .id(item.id)
                        }
                        ForEach(store.approvals) { approval in
                            approvalCard(approval)
                                .id(approval.id)
                        }
                    }
                    .padding(16)
                }
                .onChange(of: store.messages.count) { _ in scrollToBottom(proxy) }
                .onChange(of: store.approvals.count) { _ in scrollToBottom(proxy) }
                .onAppear { scrollToBottom(proxy, animated: false) }
            }
            Divider()
            composer
        }
    }

    private var emptyChat: some View {
        VStack(spacing: 10) {
            Image(systemName: "message.fill")
                .font(.largeTitle)
                .foregroundColor(.accentColor)
            Text("Hermes на связи")
                .font(.title2.bold())
            Text("Напишите сообщение. Ответ придёт от действующего агента на Windows.")
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.vertical, 48)
        .accessibilityElement(children: .combine)
    }

    private func messageBubble(_ item: ChatMessage) -> some View {
        HStack(alignment: .bottom) {
            if item.role == .user { Spacer(minLength: 48) }
            VStack(alignment: .leading, spacing: 5) {
                Text(item.text)
                    .textSelection(.enabled)
                if item.status == "failed" {
                    Label("Не отправлено", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundColor(.red)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                item.role == .user ? Color.accentColor : Color(.secondarySystemGroupedBackground),
                in: RoundedRectangle(cornerRadius: 18, style: .continuous)
            )
            .foregroundColor(item.role == .user ? .black : .primary)
            if item.role == .assistant { Spacer(minLength: 48) }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(item.role == .user ? "Вы" : "Работяга")
    }

    private func approvalCard(_ approval: PendingApproval) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(
                approval.kind == "clarify" ? "Нужен ваш ответ" : "Нужно подтверждение",
                systemImage: "hand.raised.fill"
            )
            .font(.headline)
            .foregroundColor(.orange)
            Text(approval.title)
            if let command = approval.command, !command.isEmpty {
                Text(command)
                    .font(.caption.monospaced())
                    .foregroundColor(.secondary)
                    .textSelection(.enabled)
            }
            ForEach(approval.choices, id: \.self) { choice in
                Button(choice) {
                    Task { await store.respond(to: approval, choice: choice) }
                }
                .buttonStyle(.bordered)
                .frame(maxWidth: .infinity, alignment: .leading)
                .disabled(store.isSending)
            }
            Text("Без выбора действие не выполняется.")
                .font(.footnote)
                .foregroundColor(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 16))
        .accessibilityElement(children: .contain)
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Сообщение Работяге", text: $message)
                .textFieldStyle(.roundedBorder)
                .focused($composerFocused)
                .submitLabel(.send)
                .onSubmit { sendMessage() }
                .disabled(store.isSending)
                .accessibilityHint("Отправляет сообщение действующему Hermes Agent")
            Button(action: sendMessage) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title)
                    .frame(minWidth: 44, minHeight: 44)
            }
            .disabled(message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isSending)
            .accessibilityLabel("Отправить сообщение")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial)
    }

    private var connectionLabel: some View {
        HStack(spacing: 6) {
            if store.connectionStatus == "working" || store.isRefreshing {
                ProgressView().controlSize(.small)
            } else {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)
            }
            Text(statusTitle)
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Статус Hermes: \(statusTitle)")
    }

    private func errorBanner(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(.orange)
            Text(text)
                .font(.footnote)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button("Повторить") {
                Task { await store.retryLastSubmission() }
            }
            .font(.footnote.bold())
        }
        .padding(12)
        .background(Color.orange.opacity(0.12))
    }

    private var statusTitle: String {
        switch store.connectionStatus {
        case "ready": return "На связи"
        case "working": return store.statusText ?? "Работает"
        case "waiting": return "Ждёт ответа"
        case "error": return "Ошибка"
        default: return "Нет связи"
        }
    }

    private var statusColor: Color {
        switch store.connectionStatus {
        case "ready": return .green
        case "waiting": return .orange
        case "error": return .red
        default: return .secondary
        }
    }

    private func sendMessage() {
        let outgoing = message
        guard !outgoing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        message = ""
        Task { await store.send(outgoing) }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool = true) {
        guard let lastID = store.approvals.last?.id ?? store.messages.last?.id else { return }
        if animated {
            withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(lastID, anchor: .bottom) }
        } else {
            proxy.scrollTo(lastID, anchor: .bottom)
        }
    }
}
