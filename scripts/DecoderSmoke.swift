import Foundation

@main
enum DecoderSmoke {
    static func main() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .secondsSince1970

        let pair = try decoder.decode(
            PairResponse.self,
            from: Data(#"{"device_id":"device-1","secret":"secret-1","algorithm":"HMAC-SHA256"}"#.utf8)
        )
        precondition(pair.deviceID == "device-1")

        let state = try decoder.decode(
            ChatStateResponse.self,
            from: Data(#"{"session_id":"session-1","status":"ready","status_text":null,"messages":[{"id":"message-1","role":"user","text":"hello","request_id":"request-1","status":"complete","created_at":1}],"approvals":[{"prompt_id":"prompt-1","kind":"question","title":"Continue?","command":null,"choices":["yes"],"created_at":2}],"updated_at":3}"#.utf8)
        )
        precondition(state.sessionID == "session-1")
        precondition(state.messages.first?.requestID == "request-1")
        precondition(state.approvals.first?.promptID == "prompt-1")

        let submission = try decoder.decode(
            SubmissionResponse.self,
            from: Data(#"{"request_id":"request-1","admission_id":"admission-1","status":"working"}"#.utf8)
        )
        precondition(submission.requestID == "request-1")
        precondition(submission.admissionID == "admission-1")
    }
}
