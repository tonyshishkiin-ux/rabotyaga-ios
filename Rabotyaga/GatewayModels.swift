import Foundation

struct ChatMessage: Codable, Identifiable, Equatable {
    enum Role: String, Codable {
        case user
        case assistant
    }

    let id: String
    let role: Role
    let text: String
    let requestID: String?
    var status: String
    let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case id, role, text, status, createdAt
        case requestID = "requestId"
    }
}

struct PendingApproval: Codable, Identifiable, Equatable {
    var id: String { promptID }
    let promptID: String
    let kind: String
    let title: String
    let command: String?
    let choices: [String]
    let createdAt: Date

    private enum CodingKeys: String, CodingKey {
        case kind, title, command, choices, createdAt
        case promptID = "promptId"
    }
}

struct ChatStateResponse: Codable {
    let sessionID: String?
    let status: String
    let statusText: String?
    let messages: [ChatMessage]
    let approvals: [PendingApproval]
    let updatedAt: Date

    private enum CodingKeys: String, CodingKey {
        case status, statusText, messages, approvals, updatedAt
        case sessionID = "sessionId"
    }
}

struct PairResponse: Codable {
    let deviceID: String
    let secret: String
    let algorithm: String

    private enum CodingKeys: String, CodingKey {
        case secret, algorithm
        case deviceID = "deviceId"
    }
}

struct SubmissionResponse: Codable {
    let requestID: String
    let admissionID: String?
    let status: String

    private enum CodingKeys: String, CodingKey {
        case status
        case requestID = "requestId"
        case admissionID = "admissionId"
    }
}

struct GatewayStreamEvent: Decodable {
    let sequence: Int
    let type: String
    let state: ChatStateResponse?
    let message: ChatMessage?
    let status: String?
    let statusText: String?
    let approvals: [PendingApproval]?
}

struct GatewayErrorResponse: Codable {
    let error: String
    let message: String?
}

struct GatewayCredentials: Codable {
    let deviceID: String
    let secret: String
}
