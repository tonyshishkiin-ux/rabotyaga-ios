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
    @Published private(set) var streamRevision = 0
    @Published var errorMessage: String?

    private let client = HermesGatewayClient()
    private var streamTask: Task<Void, Never>?
    private var cacheTask: Task<Void, Never>?
    private var failedSubmission: (id: String, text: String)?

    init() {
        isConfigured = client.hasCredentials()
        messages = Self.loadCachedMessages()
    }

    deinit {
        streamTask?.cancel()
        cacheTask?.cancel()
    }

    func refresh(showActivity: Bool = true) async {
        guard isConfigured else { return }
        if showActivity { isRefreshing = true }
        defer { if showActivity { isRefreshing = false } }
        do {
            let state = try await client.fetchState()
            apply(state)
            startStreaming()
            errorMessage = nil
        } catch {
            connectionStatus = "offline"
            statusText = "Нет связи со шлюзом"
            if showActivity { errorMessage = error.localizedDescription }
            startStreaming()
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
            if let index = messages.firstIndex(where: { $0.requestID == requestID && $0.role == .user }) {
                messages[index].status = "queued"
            }
            connectionStatus = "working"
            statusText = "Думает"
            scheduleCache()
            startStreaming()
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
            connectionStatus = "working"
            statusText = "Думает"
            startStreaming()
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
        streamTask?.cancel()
        cacheTask?.cancel()
        streamTask = nil
        isConfigured = false
        connectionStatus = "offline"
        statusText = nil
        approvals = []
    }

    private func startStreaming() {
        guard isConfigured, streamTask == nil else { return }
        streamTask = Task { [weak self] in
            var delay: UInt64 = 1
            while let self, self.isConfigured, !Task.isCancelled {
                do {
                    let events = try self.client.streamEvents()
                    for try await event in events {
                        guard !Task.isCancelled else { return }
                        self.apply(event)
                        self.errorMessage = nil
                        delay = 1
                    }
                } catch is CancellationError {
                    return
                } catch {
                    self.connectionStatus = "offline"
                    self.statusText = "Переподключение…"
                }
                guard !Task.isCancelled, self.isConfigured else { return }
                try? await Task.sleep(nanoseconds: delay * 1_000_000_000)
                delay = min(delay * 2, 30)
            }
            self?.streamTask = nil
        }
    }

    private func apply(_ state: ChatStateResponse) {
        messages = state.messages
        approvals = state.approvals
        connectionStatus = state.status
        statusText = state.statusText
        Self.cache(messages)
        streamRevision += 1
    }

    private func apply(_ event: GatewayStreamEvent) {
        switch event.type {
        case "state":
            if let state = event.state { apply(state) }
        case "message":
            if let message = event.message { apply(message) }
        case "status":
            connectionStatus = event.status ?? connectionStatus
            statusText = event.statusText
        case "approvals":
            approvals = event.approvals ?? []
            streamRevision += 1
        case "revoked":
            disconnectLocally()
        default:
            break
        }
    }

    private func apply(_ message: ChatMessage) {
        if let index = messages.firstIndex(where: { $0.id == message.id }) {
            messages[index] = message
        } else if let requestID = message.requestID,
                  let index = messages.firstIndex(where: {
                      $0.requestID == requestID && $0.role == message.role
                  }) {
            messages[index] = message
        } else {
            messages.append(message)
        }
        if message.role == .assistant && message.status == "streaming" {
            connectionStatus = "working"
            statusText = "Пишет ответ"
        }
        streamRevision += 1
        scheduleCache()
    }

    private func scheduleCache() {
        cacheTask?.cancel()
        cacheTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard let self, !Task.isCancelled else { return }
            Self.cache(self.messages)
        }
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
