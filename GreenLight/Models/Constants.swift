import Foundation

struct Constants {
    struct Detection {
        static let stationarySpeedThresholdMPH: Double = 2.0
        static let redConfirmFrames = 3
        static let greenConfirmFrames = 2
        static let minimumAreaFraction = 0.005
        static let topFraction = 0.60
        static let centerFraction = 0.70
    }

    struct Chime {
        static let cooldownSeconds: TimeInterval = 20.0
        static let redMemorySeconds: TimeInterval = 8.0
        static let resourceName = "chime"
    }

    static let urlObjectDetection = URL(string: "https://www.neuralception.com/objectdetection")!
}
