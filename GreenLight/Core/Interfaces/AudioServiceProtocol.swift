import Foundation

protocol AudioServiceProtocol: Sendable {
    var isMuted: Bool { get async }
    func setMuted(_ muted: Bool) async
    func play()
}
