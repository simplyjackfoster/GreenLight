import Foundation
import UIKit

struct Constants {
    struct BoxColours {
        static let misc = CGColor(red: 100.0 / 255.0, green: 149.0 / 255.0, blue: 237.0 / 255.0, alpha: 1.0)
        static let trafficRed = CGColor(red: 255.0 / 255.0, green: 30.0 / 255.0, blue: 0.0 / 255.0, alpha: 1.0)
        static let trafficNa = CGColor(red: 249.0 / 255.0, green: 205.0 / 255.0, blue: 62.0 / 255.0, alpha: 1.0)
        static let trafficGreen = CGColor(red: 8.0 / 255.0, green: 206.0 / 255.0, blue: 22.0 / 255.0, alpha: 1.0)
        static let pedestrian = CGColor(red: 255.0 / 255.0, green: 165.0 / 255.0, blue: 0.0 / 255.0, alpha: 1.0)
    }

    struct TextColours {
        static let light = CGColor(red: 241.0 / 255.0, green: 241.0 / 255.0, blue: 241.0 / 255.0, alpha: 1.0)
        static let dark = CGColor(red: 47.0 / 255.0, green: 46.0 / 255.0, blue: 42.0 / 255.0, alpha: 1.0)
    }

    struct InterfaceColours {
        static let navigation = CGColor(red: 47.0 / 255.0, green: 46.0 / 255.0, blue: 42.0 / 255.0, alpha: 1.0)
    }

    struct Detection {
        static let stationarySpeedThresholdMPH: Double = 2.0
        static let redConfirmFrames = 3
        static let greenConfirmFrames = 2
        static let minimumAreaFraction: CGFloat = 0.005
        static let topFraction: CGFloat = 0.60
        static let centerFraction: CGFloat = 0.70
    }

    struct Chime {
        static let cooldownSeconds: TimeInterval = 20.0
        static let resourceName = "chime"
    }

    static let urlObjectDetection = "https://www.neuralception.com/objectdetection"
}
