import CryptoKit
import Foundation

enum GatewayClientError: LocalizedError {
    case notConfigured
    case invalidURL
    case insecureURL
    case invalidResponse
    case networkUnavailable
    case timedOut
    case cannotReachGateway
    case tlsValidationFailed
    case server(Int, String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Подключение к Hermes ещё не настроено"
        case .invalidURL:
            return "Укажите корректный адрес шлюза"
        case .insecureURL:
            return "Для iPhone разрешён только защищённый адрес HTTPS"
        case .invalidResponse:
            return "Шлюз вернул неожиданный ответ"
        case .networkUnavailable:
            return "Нет подключения к интернету. Сообщение можно повторить после восстановления сети"
        case .timedOut:
            return "Шлюз не ответил вовремя. Проверьте интернет и повторите попытку"
        case .cannotReachGateway:
            return "Не удалось связаться со шлюзом Работяги"
        case .tlsValidationFailed:
            return "Не удалось проверить защищённое HTTPS-соединение"
        case .server(_, let message):
            return message
        }
    }
}

struct HermesGatewayClient {
    static let gatewayURLKey = "hermes.gateway.url.v1"
    private static let publicGatewayURL = "https://rabotyaga.viralops.ru"

    private let keychain = KeychainStore()
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init() {
        Self.migratePrivateGatewayURLIfNeeded()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 300
        session = URLSession(configuration: configuration)
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .secondsSince1970
        encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
    }

    private static func migratePrivateGatewayURLIfNeeded() {
        let defaults = UserDefaults.standard
        guard let storedURL = defaults.string(forKey: gatewayURLKey),
              let host = URLComponents(string: storedURL)?.host?.lowercased(),
              host.hasSuffix(".ts.net") else { return }
        defaults.set(publicGatewayURL, forKey: gatewayURLKey)
    }

    func normalizedBaseURL(_ rawValue: String) throws -> URL {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: trimmed),
              components.host != nil else { throw GatewayClientError.invalidURL }
        guard components.scheme?.lowercased() == "https" else {
            throw GatewayClientError.insecureURL
        }
        components.path = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.query = nil
        components.fragment = nil
        guard let url = components.url else { throw GatewayClientError.invalidURL }
        return url
    }

    func pair(baseURL rawURL: String, code: String, deviceName: String) async throws {
        let baseURL = try normalizedBaseURL(rawURL)
        let payload = ["code": code, "device_name": deviceName]
        let response: PairResponse = try await request(
            baseURL: baseURL,
            path: "/v1/pair",
            method: "POST",
            body: try encoder.encode(payload),
            authenticated: false
        )
        guard response.algorithm == "HMAC-SHA256" else { throw GatewayClientError.invalidResponse }
        try keychain.save(GatewayCredentials(deviceID: response.deviceID, secret: response.secret))
        UserDefaults.standard.set(baseURL.absoluteString, forKey: Self.gatewayURLKey)
    }

    func fetchState() async throws -> ChatStateResponse {
        try await authenticatedRequest(path: "/v1/chat", method: "GET", body: Data())
    }

    func submit(text: String, requestID: String) async throws -> SubmissionResponse {
        let payload = ["request_id": requestID, "text": text]
        return try await authenticatedRequest(
            path: "/v1/chat/messages", method: "POST", body: try encoder.encode(payload)
        )
    }

    func respond(to approval: PendingApproval, choice: String, requestID: String) async throws {
        let payload = ["request_id": requestID, "choice": choice]
        let _: SubmissionResponse = try await authenticatedRequest(
            path: "/v1/chat/approvals/\(approval.promptID)",
            method: "POST",
            body: try encoder.encode(payload)
        )
    }

    func revoke() async throws {
        struct RevokeResponse: Codable { let revoked: Bool }
        let _: RevokeResponse = try await authenticatedRequest(
            path: "/v1/device", method: "DELETE", body: Data()
        )
        try keychain.delete()
    }

    func hasCredentials() -> Bool {
        (try? keychain.load()) != nil
    }

    func clearLocalCredentials() throws {
        try keychain.delete()
    }

    private func authenticatedRequest<Response: Decodable>(
        path: String, method: String, body: Data
    ) async throws -> Response {
        guard let rawURL = UserDefaults.standard.string(forKey: Self.gatewayURLKey),
              let credentials = try keychain.load() else {
            throw GatewayClientError.notConfigured
        }
        return try await request(
            baseURL: normalizedBaseURL(rawURL),
            path: path,
            method: method,
            body: body,
            authenticated: true,
            credentials: credentials
        )
    }

    private func request<Response: Decodable>(
        baseURL: URL,
        path: String,
        method: String,
        body: Data,
        authenticated: Bool,
        credentials: GatewayCredentials? = nil
    ) async throws -> Response {
        guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else {
            throw GatewayClientError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body.isEmpty ? nil : body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        if authenticated {
            guard let credentials else { throw GatewayClientError.notConfigured }
            sign(&request, body: body, path: path, credentials: credentials)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            switch error.code {
            case .notConnectedToInternet, .dataNotAllowed, .internationalRoamingOff:
                throw GatewayClientError.networkUnavailable
            case .timedOut:
                throw GatewayClientError.timedOut
            case .secureConnectionFailed, .serverCertificateHasBadDate,
                 .serverCertificateUntrusted, .serverCertificateHasUnknownRoot,
                 .serverCertificateNotYetValid, .clientCertificateRejected:
                throw GatewayClientError.tlsValidationFailed
            case .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed,
                 .networkConnectionLost:
                throw GatewayClientError.cannotReachGateway
            default:
                throw error
            }
        }
        guard let http = response as? HTTPURLResponse else { throw GatewayClientError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let serverError = try? decoder.decode(GatewayErrorResponse.self, from: data)
            throw GatewayClientError.server(
                http.statusCode,
                serverError?.message ?? "Шлюз вернул ошибку \(http.statusCode)"
            )
        }
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw GatewayClientError.invalidResponse
        }
    }

    private func sign(
        _ request: inout URLRequest,
        body: Data,
        path: String,
        credentials: GatewayCredentials
    ) {
        let timestamp = Int(Date().timeIntervalSince1970)
        let nonce = UUID().uuidString.lowercased()
        let bodyHash = SHA256.hash(data: body).map { String(format: "%02x", $0) }.joined()
        let canonical = "\(request.httpMethod ?? "GET")\n\(path)\n\(timestamp)\n\(nonce)\n\(bodyHash)"
        let derivedKey = SHA256.hash(data: Data(credentials.secret.utf8))
        let signature = HMAC<SHA256>.authenticationCode(
            for: Data(canonical.utf8),
            using: SymmetricKey(data: Data(derivedKey))
        )
        let encoded = Data(signature).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        request.setValue(credentials.deviceID, forHTTPHeaderField: "X-Rabotyaga-Device")
        request.setValue(String(timestamp), forHTTPHeaderField: "X-Rabotyaga-Timestamp")
        request.setValue(nonce, forHTTPHeaderField: "X-Rabotyaga-Nonce")
        request.setValue(encoded, forHTTPHeaderField: "X-Rabotyaga-Signature")
    }
}
