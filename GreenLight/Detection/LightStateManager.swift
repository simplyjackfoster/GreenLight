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

/// Observed-light fallback for noisy frame-to-frame transitions.
/// Uses geometry-filtered light when available, but can fall back to any observed light.
final class LightTransitionFallbackState {

    let cooldownDuration: TimeInterval
    let redMemoryDuration: TimeInterval

    private var lastRedSeenAt: Date?
    private var lastChimeAt: Date?

    init(
        cooldownDuration: TimeInterval = Constants.Chime.cooldownSeconds,
        redMemoryDuration: TimeInterval = Constants.Chime.redMemorySeconds
    ) {
        self.cooldownDuration = cooldownDuration
        self.redMemoryDuration = redMemoryDuration
    }

    @discardableResult
    func update(
        filteredLight: DetectedLightColor,
        observedLight: DetectedLightColor,
        isStationary: Bool,
        now: Date = Date()
    ) -> Bool {
        let effectiveLight = effectiveLight(filteredLight: filteredLight, observedLight: observedLight)

        if effectiveLight == .red {
            lastRedSeenAt = now
            return false
        }

        guard effectiveLight == .green, isStationary else { return false }

        guard let lastRedSeenAt else { return false }
        let elapsedSinceRed = now.timeIntervalSince(lastRedSeenAt)
        guard elapsedSinceRed <= redMemoryDuration else {
            self.lastRedSeenAt = nil
            return false
        }

        if let lastChimeAt, now.timeIntervalSince(lastChimeAt) < cooldownDuration {
            return false
        }

        self.lastChimeAt = now
        self.lastRedSeenAt = nil
        return true
    }

    func reset() {
        lastRedSeenAt = nil
        lastChimeAt = nil
    }

    private func effectiveLight(
        filteredLight: DetectedLightColor,
        observedLight: DetectedLightColor
    ) -> DetectedLightColor {
        if filteredLight == .red || filteredLight == .green {
            return filteredLight
        }
        if observedLight == .red || observedLight == .green {
            return observedLight
        }
        return .none
    }
}
