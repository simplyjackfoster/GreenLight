import CoreML
import CoreVideo
import Foundation

final class TrafficLightStateClassifier {
    static let shared = TrafficLightStateClassifier()

    private let model: MLModel?
    private let inputWidth = 64
    private let inputHeight = 64

    private init() {
        let configuration = MLModelConfiguration()
        configuration.computeUnits = .cpuAndGPU

        if let compiledURL = Bundle.main.url(forResource: "traffic_light_state_classifier", withExtension: "mlmodelc") {
            model = try? MLModel(contentsOf: compiledURL, configuration: configuration)
            return
        }

        if let packageURL = Bundle.main.url(forResource: "traffic_light_state_classifier", withExtension: "mlpackage") {
            model = try? MLModel(contentsOf: packageURL, configuration: configuration)
            return
        }

        model = nil
    }

    func classify(pixelBuffer: CVPixelBuffer, boundingBox: CGRect) -> DetectedLightColor? {
        guard let model else { return nil }
        let normalized = normalizedRect(boundingBox)
        guard normalized.width > 0.001, normalized.height > 0.001 else { return nil }
        guard let input = makeInputArray(pixelBuffer: pixelBuffer, normalizedRect: normalized) else {
            return nil
        }

        guard let prediction = try? model.prediction(from: ClassifierInput(input: input)) else {
            return nil
        }

        if let label = prediction.featureValue(for: "classLabel")?.stringValue {
            return mapLabel(label)
        }

        return nil
    }

    private func mapLabel(_ label: String) -> DetectedLightColor {
        let key = label.lowercased()
        if key.contains("red") { return .red }
        if key.contains("green") { return .green }
        if key.contains("yellow") { return .yellow }
        if key.contains("off") || key.contains("hard_negative") { return .none }
        return .unknown
    }

    private func normalizedRect(_ rect: CGRect) -> CGRect {
        let unit = CGRect(x: 0, y: 0, width: 1, height: 1)
        return rect.standardized.intersection(unit)
    }

    private func makeInputArray(pixelBuffer: CVPixelBuffer, normalizedRect: CGRect) -> MLMultiArray? {
        guard let array = try? MLMultiArray(shape: [1, 3, NSNumber(value: inputHeight), NSNumber(value: inputWidth)], dataType: .float32) else {
            return nil
        }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        guard width > 0, height > 0 else { return nil }

        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let mean: [Float] = [0.485, 0.456, 0.406]
        let std: [Float] = [0.229, 0.224, 0.225]

        for y in 0..<inputHeight {
            for x in 0..<inputWidth {
                let nx = normalizedRect.minX + normalizedRect.width * (CGFloat(x) + 0.5) / CGFloat(inputWidth)
                let ny = normalizedRect.minY + normalizedRect.height * (CGFloat(y) + 0.5) / CGFloat(inputHeight)

                let px = max(0, min(width - 1, Int(nx * CGFloat(width))))
                let py = max(0, min(height - 1, Int((1.0 - ny) * CGFloat(height))))

                let rgb = sampleRGB(pixelBuffer: pixelBuffer, x: px, y: py)
                let r = (Float(rgb.r) - mean[0]) / std[0]
                let g = (Float(rgb.g) - mean[1]) / std[1]
                let b = (Float(rgb.b) - mean[2]) / std[2]

                array[[0, 0, NSNumber(value: y), NSNumber(value: x)]] = NSNumber(value: r)
                array[[0, 1, NSNumber(value: y), NSNumber(value: x)]] = NSNumber(value: g)
                array[[0, 2, NSNumber(value: y), NSNumber(value: x)]] = NSNumber(value: b)
            }
        }

        return array
    }

    private func sampleRGB(pixelBuffer: CVPixelBuffer, x: Int, y: Int) -> (r: Double, g: Double, b: Double) {
        guard let yPlane = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0),
              let uvPlane = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 1) else {
            return (0, 0, 0)
        }

        let yStride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)
        let uvStride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 1)

        let yValue = Double(yPlane.load(fromByteOffset: y * yStride + x, as: UInt8.self))
        let uvX = (x / 2) * 2
        let uvY = y / 2
        let cbValue = Double(uvPlane.load(fromByteOffset: uvY * uvStride + uvX, as: UInt8.self))
        let crValue = Double(uvPlane.load(fromByteOffset: uvY * uvStride + uvX + 1, as: UInt8.self))

        let Y = yValue
        let Cb = cbValue - 128.0
        let Cr = crValue - 128.0

        let r = max(0.0, min(255.0, Y + 1.402 * Cr)) / 255.0
        let g = max(0.0, min(255.0, Y - 0.344136 * Cb - 0.714136 * Cr)) / 255.0
        let b = max(0.0, min(255.0, Y + 1.772 * Cb)) / 255.0
        return (r, g, b)
    }
}

private final class ClassifierInput: MLFeatureProvider {
    private let input: MLMultiArray

    init(input: MLMultiArray) {
        self.input = input
    }

    var featureNames: Set<String> { ["input"] }

    func featureValue(for featureName: String) -> MLFeatureValue? {
        guard featureName == "input" else { return nil }
        return MLFeatureValue(multiArray: input)
    }
}
