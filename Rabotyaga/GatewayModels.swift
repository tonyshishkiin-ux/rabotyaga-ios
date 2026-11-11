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
}

struct PendingApproval: Codable, Identifiable, Equatable {
    var id: String { promptID }
    let promptID: String
    let kind: String
    let title: String
    let command: String?
    let choices: [String]
    let createdAt: Date
}

struct ChatStateResponse: Codable {
    let sessionID: String?
    let status: String
    let statusText: String?
    let messages: [ChatMessage]
    let approvals: [PendingApproval]
    let updatedAt: Date
}

struct PairResponse: Codable {
    let deviceID: String
    let secret: String
    let algorithm: String
}

struct SubmissionResponse: Codable {
    let requestID: String
    let admissionID: String?
    let status: String
}

struct GatewayErrorResponse: Codable {
    let error: String
    let message: String?
}

struct GatewayCredentials: Codable {
    let deviceID: String
    let secret: String
}
