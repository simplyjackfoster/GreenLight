import Foundation

struct DetectionResult: Sendable {
    var lightColor: DetectedLightColor
    var observedColor: DetectedLightColor
    var boundingBoxes: [BoundingBox]
}
