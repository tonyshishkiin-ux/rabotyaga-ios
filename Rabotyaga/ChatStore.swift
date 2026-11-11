import Foundation

@MainActor
final class ChatStore: ObservableObject {
    @Published private(set) var messages: [ChatMessage] = []
    @Published private(set) var approvals: [PendingApproval] = []
    @Published private(set) var connectionStatus = "offline"
    @Published private(set) var statusText: String?
    @Published private(set) var isRefreshing = false
    @Published private(set) var isSending = false
    @Published private(set) var isConfigured = false
    @Published var errorMessage: String?

    private let client = HermesGatewayClient()
    private var pollingTask: Task<Void, Never>?
    private var failedSubmission: (id: String, text: String)?

    init() {
        isConfigured = client.hasCredentials()
        messages = Self.loadCachedMessages()
    }

    deinit {
        pollingTask?.cancel()
    }

    func refresh(showActivity: Bool = true) async {
        guard isConfigured else { return }
        if showActivity { isRefreshing = true }
        defer { if showActivity { isRefreshing = false } }
        do {
            let state = try await client.fetchState()
            apply(state)
            if showActivity && (state.status == "working" || state.status == "connecting") {
                startPolling()
            }
            errorMessage = nil
        } catch {
            connectionStatus = "offline"
            statusText = "Нет связи со шлюзом"
            if showActivity { errorMessage = error.localizedDescription }
        }
    }

    func send(_ rawText: String) async {
        let text = rawText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        let requestID = UUID().uuidString.lowercased()
        await submit(text, requestID: requestID)
    }

    func retryLastSubmission() async {
        guard let failedSubmission else { return }
        await submit(failedSubmission.text, requestID: failedSubmission.id)
    }

    private func submit(_ text: String, requestID: String) async {
        isSending = true
        errorMessage = nil
        let optimistic = ChatMessage(
            id: "local-\(requestID)",
            role: .user,
            text: text,
            requestID: requestID,
            status: "sending",
            createdAt: Date()
        )
        if !messages.contains(where: { $0.requestID == requestID && $0.role == .user }) {
            messages.append(optimistic)
            Self.cache(messages)
        }
        do {
            _ = try await client.submit(text: text, requestID: requestID)
            failedSubmission = nil
            await refresh(showActivity: false)
            startPolling()
        } catch {
            failedSubmission = (requestID, text)
            if let index = messages.firstIndex(where: { $0.requestID == requestID && $0.role == .user }) {
                messages[index].status = "failed"
            }
            errorMessage = error.localizedDescription
            Self.cache(messages)
        }
        isSending = false
    }

    func respond(to approval: PendingApproval, choice: String) async {
        guard !isSending else { return }
        isSending = true
        errorMessage = nil
        do {
            try await client.respond(
                to: approval,
                choice: choice,
                requestID: UUID().uuidString.lowercased()
            )
            approvals.removeAll { $0.id == approval.id }
            await refresh(showActivity: false)
            startPolling()
        } catch {
            errorMessage = error.localizedDescription
        }
        isSending = false
    }

    func pair(gatewayURL: String, code: String) async -> Bool {
        isRefreshing = true
        errorMessage = nil
        defer { isRefreshing = false }
        do {
            try await client.pair(
                baseURL: gatewayURL,
                code: code.trimmingCharacters(in: .whitespacesAndNewlines),
                deviceName: "iPhone Работяги"
            )
            isConfigured = true
            await refresh(showActivity: false)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func revoke() async -> Bool {
        isRefreshing = true
        errorMessage = nil
        defer { isRefreshing = false }
        do {
            try await client.revoke()
            disconnectLocally()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func forgetLocalCredentials() {
        do {
            try client.clearLocalCredentials()
            disconnectLocally()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func disconnectLocally() {
        pollingTask?.cancel()
        isConfigured = false
        connectionStatus = "offline"
        statusText = nil
        approvals = []
    }

    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            for _ in 0..<300 {
                guard let self, !Task.isCancelled else { return }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                await self.refresh(showActivity: false)
                if self.connectionStatus == "ready" || self.connectionStatus == "error" || !self.approvals.isEmpty {
                    return
                }
            }
        }
    }

    private func apply(_ state: ChatStateResponse) {
        messages = state.messages
        approvals = state.approvals
        connectionStatus = state.status
        statusText = state.statusText
        Self.cache(messages)
    }

    private static var cacheURL: URL? {
        guard let directory = try? FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ) else { return nil }
        return directory.appendingPathComponent("rabotyaga-chat-cache-v1.json")
    }

    private static func loadCachedMessages() -> [ChatMessage] {
        guard let url = cacheURL,
              let data = try? Data(contentsOf: url) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970
        return (try? decoder.decode([ChatMessage].self, from: data)) ?? []
    }

    private static func cache(_ messages: [ChatMessage]) {
        guard let url = cacheURL else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .secondsSince1970
        guard let data = try? encoder.encode(messages),
              (try? data.write(to: url, options: .atomic)) != nil else { return }
        try? FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
    }
}
