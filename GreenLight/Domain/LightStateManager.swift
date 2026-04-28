import Foundation

final class LightStateManager {
    private enum InternalState { case idle, trackingRed(Int), confirmedRed, transitioningToGreen(Int), cooldown }

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
    func update(detectedLight: DetectedLightColor, speedStatus: SpeedStatus, now: Date = Date()) -> Bool {
        if case .cooldown = internalState {
            guard let start = cooldownStart, now.timeIntervalSince(start) >= cooldownDuration else { return false }
            internalState = .idle
            cooldownStart = nil
        }

        switch (internalState, detectedLight) {
        case (.idle, .red): internalState = .trackingRed(1)
        case (.trackingRed(let c), .red):
            let next = c + 1
            internalState = next >= redConfirmCount ? .confirmedRed : .trackingRed(next)
        case (.confirmedRed, .green):
            internalState = speedStatus == .knownStationary ? .transitioningToGreen(1) : .idle
        case (.transitioningToGreen(let c), .green):
            guard speedStatus == .knownStationary else { internalState = .idle; return false }
            let next = c + 1
            if next >= greenConfirmCount {
                internalState = .cooldown
                cooldownStart = now
                return true
            }
            internalState = .transitioningToGreen(next)
        case (.trackingRed, _), (.confirmedRed, .none), (.confirmedRed, .yellow),
             (.transitioningToGreen, .none), (.transitioningToGreen, .red), (.transitioningToGreen, .yellow):
            internalState = .idle
        default: break
        }

        return false
    }

    var displayState: DisplayLightState {
        switch internalState {
        case .idle: return .unknown
        case .trackingRed, .confirmedRed: return .red
        case .transitioningToGreen, .cooldown: return .green
        }
    }

    var isTrackingRedOrTransitioning: Bool {
        switch internalState {
        case .trackingRed, .confirmedRed, .transitioningToGreen: return true
        default: return false
        }
    }
}

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
    func update(filteredLight: DetectedLightColor, observedLight: DetectedLightColor, speedStatus: SpeedStatus, now: Date = Date()) -> Bool {
        let effectiveLight: DetectedLightColor = (filteredLight == .red || filteredLight == .green) ? filteredLight : observedLight
        if effectiveLight == .red { lastRedSeenAt = now; return false }
        guard effectiveLight == .green, speedStatus == .knownStationary else { return false }
        guard let lastRedSeenAt, now.timeIntervalSince(lastRedSeenAt) <= redMemoryDuration else { self.lastRedSeenAt = nil; return false }
        if let lastChimeAt, now.timeIntervalSince(lastChimeAt) < cooldownDuration { return false }
        self.lastChimeAt = now
        self.lastRedSeenAt = nil
        return true
    }
}
