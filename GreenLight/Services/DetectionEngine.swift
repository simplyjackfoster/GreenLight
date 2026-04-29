import CoreML
@preconcurrency import CoreVideo
import Foundation
import Vision

actor DetectionEngine: DetectionEngineProtocol {

    let results: AsyncStream<DetectionResult>
    private let resultsContinuation: AsyncStream<DetectionResult>.Continuation
    private var consumeTask: Task<Void, Never>?
    private var request: VNCoreMLRequest?

    init() {
        var cont: AsyncStream<DetectionResult>.Continuation!
        results = AsyncStream(bufferingPolicy: .bufferingNewest(1)) { cont = $0 }
        resultsContinuation = cont
        if let model = Self.loadVisionModel() {
            request = Self.makeRequest(model: model)
        } else {
            request = nil
        }
    }

    func attach(camera: any CameraServiceProtocol) async {
        consumeTask?.cancel()
        let request = self.request
        let frames = await camera.frames
        consumeTask = Task { [weak self] in
            guard let self else { return }
            for await frame in frames {
                if Task.isCancelled { break }
                let pixelBuffer = frame.pixelBuffer
                let result = Self.runInference(on: pixelBuffer, request: request)
                await self.emit(result)
            }
        }
    }

    private func emit(_ result: DetectionResult) {
        resultsContinuation.yield(result)
    }

    private static func makeRequest(model: VNCoreMLModel) -> VNCoreMLRequest {
        let request = VNCoreMLRequest(model: model)
        request.imageCropAndScaleOption = .scaleFill
        return request
    }

    private static func runInference(on pixelBuffer: CVPixelBuffer, request: VNCoreMLRequest?) -> DetectionResult {
        guard let request else {
            return DetectionResult(lightColor: .unknown, observedColor: .unknown, boundingBoxes: [])
        }
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .right)
        do {
            try handler.perform([request])
        } catch {
            return DetectionResult(lightColor: .unknown, observedColor: .unknown, boundingBoxes: [])
        }

        var bestFilteredLightColor: DetectedLightColor = .none
        var bestFilteredConfidence: Float = 0
        var bestObservedLightColor: DetectedLightColor = .none
        var bestObservedConfidence: Float = 0
        var boxes: [BoundingBox] = []

        for observation in (request.results as? [VNRecognizedObjectObservation]) ?? [] {
            guard let top = observation.labels.first else { continue }
            let lightColor = Self.resolveTrafficLightColor(label: top.identifier, box: observation.boundingBox, pixelBuffer: pixelBuffer)
            boxes.append(BoundingBox(rect: observation.boundingBox, label: top.identifier, confidence: top.confidence))

            if lightColor != .unknown, lightColor != .none, top.confidence > bestObservedConfidence {
                bestObservedLightColor = lightColor
                bestObservedConfidence = top.confidence
            }

            if lightColor != .unknown,
               lightColor != .none,
               GeometryFilter.passes(normalizedBox: observation.boundingBox),
               top.confidence > bestFilteredConfidence {
                bestFilteredLightColor = lightColor
                bestFilteredConfidence = top.confidence
            }
        }

        return DetectionResult(
            lightColor: bestFilteredLightColor == .none ? .unknown : bestFilteredLightColor,
            observedColor: bestObservedLightColor == .none ? .unknown : bestObservedLightColor,
            boundingBoxes: boxes
        )
    }

    private static func resolveTrafficLightColor(
        label: String,
        box: CGRect,
        pixelBuffer: CVPixelBuffer
    ) -> DetectedLightColor {
        switch label {
        case "traffic_light_red":
            return .red
        case "traffic_light_green":
            return .green
        case "traffic_light_na":
            return .yellow
        case "traffic light":
            if let modelColor = TrafficLightStateClassifier.shared.classify(pixelBuffer: pixelBuffer, boundingBox: box),
               modelColor != .unknown, modelColor != .none {
                return modelColor
            }
            return ColorHeuristic.analyze(pixelBuffer: pixelBuffer, boundingBox: box)
        default:
            return .none
        }
    }

    private static let experimentalGPUDefaultsKey = "mlExperimentalEnableGPU"

    private static func preferredComputeUnits() -> [MLComputeUnits] {
        let defaults = UserDefaults.standard
        let enableExperimentalGPU = defaults.bool(forKey: experimentalGPUDefaultsKey)
        var units: [MLComputeUnits] = [.cpuAndNeuralEngine, .cpuOnly]
        if enableExperimentalGPU {
            // Experimental path: may trigger MPSGraph GPU compiler crashes for some models/devices.
            units.insert(.cpuAndGPU, at: 0)
            units.insert(.all, at: 0)
        }
        var unique: [MLComputeUnits] = []
        for unit in units where !unique.contains(unit) {
            unique.append(unit)
        }
        return unique
    }

    private static func loadVisionModel() -> VNCoreMLModel? {
        let candidates: [(String, String)] = [
            ("yolo26nTraffic", "mlmodelc"),
            ("yolo26nTraffic", "mlpackage"),
            ("yolo11nTraffic", "mlmodelc"),
            ("yolo11nTraffic", "mlpackage"),
            ("yolov8nTraffic", "mlmodelc"),
            ("yolov8nTraffic", "mlpackage"),
            ("yolov5sTraffic", "mlmodelc"),
            ("yolov5sTraffic", "mlmodel"),
        ]
        let computeUnitsOrder = preferredComputeUnits()

        for (name, ext) in candidates {
            guard let modelURL = Bundle.main.url(forResource: name, withExtension: ext) else { continue }
            for computeUnits in computeUnitsOrder {
                let config = MLModelConfiguration()
                config.computeUnits = computeUnits
                guard let mlModel = try? MLModel(contentsOf: modelURL, configuration: config),
                      let visionModel = try? VNCoreMLModel(for: mlModel) else { continue }
                return visionModel
            }
        }
        return nil
    }
}
