import Foundation

struct DetectionResult: Sendable {
    var lightColor: DetectedLightColor
    var observedColor: DetectedLightColor
    var lensSmudged: Bool
    var boundingBoxes: [BoundingBox]
}
