import Foundation

final class LightStateManager {

    private enum InternalState {
        case idle
        case trackingRed(count: Int)
        case confirmedRed
        case transitioningToGreen(count: Int)
        case cooldown
    }

    let redConfirmCount: Int
    let greenConfirmCount: Int
    let cooldownDuration: TimeInterval

    private var internalState: InternalState = .idle
    private var cooldownStart: Date?

    init(
        redConfirmCount: Int = Constants.Detection.redConfirmFrames,
        greenConfirmCount: Int = Constants.Detection.greenConfirmFrames,
        cooldownDuration: TimeInterval = Constants.Chime.cooldownSeconds
    ) {
        self.redConfirmCount = redConfirmCount
        self.greenConfirmCount = greenConfirmCount
        self.cooldownDuration = cooldownDuration
    }

    @discardableResult
    func update(
        detectedLight: DetectedLightColor,
        isStationary: Bool,
        now: Date = Date()
    ) -> Bool {
        if case .cooldown = internalState {
            guard let start = cooldownStart,
                  now.timeIntervalSince(start) >= cooldownDuration else {
                return false
            }
            internalState = .idle
            cooldownStart = nil
        }

        switch (internalState, detectedLight, isStationary) {
        case (.idle, .red, _):
            internalState = .trackingRed(count: 1)

        case (.trackingRed(let count), .red, _):
            let next = count + 1
            internalState = next >= redConfirmCount ? .confirmedRed : .trackingRed(count: next)

        case (.confirmedRed, .green, true):
            internalState = .transitioningToGreen(count: 1)

        case (.confirmedRed, .green, false):
            internalState = .idle

        case (.transitioningToGreen(let count), .green, true):
            let next = count + 1
            if next >= greenConfirmCount {
                internalState = .cooldown
                cooldownStart = now
                return true
            }
            internalState = .transitioningToGreen(count: next)

        case (.transitioningToGreen, .green, false):
            internalState = .idle

        case (.trackingRed, _, _),
             (.confirmedRed, .none, _),
             (.confirmedRed, .yellow, _),
             (.transitioningToGreen, .none, _),
             (.transitioningToGreen, .red, _),
             (.transitioningToGreen, .yellow, _):
            internalState = .idle

        default:
            break
        }

        return false
    }

    func reset() {
        internalState = .idle
        cooldownStart = nil
    }

    var displayState: DetectedLightColor {
        switch internalState {
        case .idle:
            return .unknown
        case .trackingRed, .confirmedRed:
            return .red
        case .transitioningToGreen, .cooldown:
            return .green
        }
    }
}
