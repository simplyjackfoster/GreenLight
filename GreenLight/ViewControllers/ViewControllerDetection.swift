import AVFoundation
import CoreML
import UIKit
import Vision

class ViewControllerDetection: ViewController {

    private let detectionState = DetectionState.shared
    private let stateManager = LightStateManager()
    private let chimeController = ChimeController()

    private var detectionOverlay: CALayer!
    private var requests = [VNRequest]()
    private var currentPixelBuffer: CVPixelBuffer?
    private var previousObservedLight: DetectedLightColor = .none
    private let fallbackState = LightTransitionFallbackState()

    private func resolveModelURL() -> URL? {
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

        for (name, ext) in candidates {
            if let url = Bundle.main.url(forResource: name, withExtension: ext) {
                return url
            }
        }
        return nil
    }

    @discardableResult
    func setupVision() -> NSError? {
        guard let modelURL = resolveModelURL() else {
            return NSError(
                domain: "ViewControllerDetection",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "ML model not found (expected yolo26nTraffic/yolo11nTraffic/yolov8nTraffic/yolov5sTraffic)"]
            )
        }

        do {
            let configuration = MLModelConfiguration()
            configuration.computeUnits = .cpuAndGPU
            let mlModel = try MLModel(contentsOf: modelURL, configuration: configuration)
            let visionModel = try VNCoreMLModel(for: mlModel)
            let request = VNCoreMLRequest(model: visionModel) { [weak self] request, _ in
                guard let self, let results = request.results else { return }
                DispatchQueue.main.async {
                    self.handleResults(results)
                }
            }
            request.imageCropAndScaleOption = .scaleFill
            requests = [request]
        } catch {
            print("[ViewControllerDetection] Model setup failed: \(error)")
            return error as NSError
        }

        return nil
    }

    override func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        currentPixelBuffer = pixelBuffer

        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .right)
        do {
            try handler.perform(requests)
        } catch {
            print("[ViewControllerDetection] Inference failed: \(error)")
        }
    }

    @MainActor
    private func handleResults(_ results: [Any]) {
        detectionOverlay.sublayers = nil

        let threshold = detectionState.sensitivity.confidenceThreshold
        var bestFilteredLightColor: DetectedLightColor = .none
        var bestFilteredConfidence: Float = 0
        var bestObservedLightColor: DetectedLightColor = .none
        var bestObservedConfidence: Float = 0

        for observation in results.compactMap({ $0 as? VNRecognizedObjectObservation }) {
            guard let top = observation.labels.first,
                  Double(top.confidence) >= threshold else { continue }

            let label = top.identifier
            let box = observation.boundingBox

            let lightColor = resolveTrafficLightColor(label: label, box: box)
            if lightColor != .unknown, lightColor != .none,
               top.confidence > bestObservedConfidence {
                bestObservedLightColor = lightColor
                bestObservedConfidence = top.confidence
            }

            if lightColor != .unknown, lightColor != .none,
               GeometryFilter.passes(normalizedBox: box),
               top.confidence > bestFilteredConfidence {
                bestFilteredLightColor = lightColor
                bestFilteredConfidence = top.confidence
            }

            let objectBounds = VNImageRectForNormalizedRect(box, Int(bufferSize.width), Int(bufferSize.height))

            if boolDefaultTrue("visualizeDetections") {
                detectionOverlay.addSublayer(drawBox(objectBounds, label: label))
            }
            if boolDefaultTrue("showLabels") {
                detectionOverlay.addSublayer(drawLabel(objectBounds, label: label, confidence: top.confidence))
            }
        }

        let speedStatus = detectionState.speedStatus

        let stateMachineChime = stateManager.update(
            detectedLight: bestFilteredLightColor,
            speedStatus: speedStatus
        )

        let fallbackChime = stateManager.isTrackingRedOrTransitioning && fallbackState.update(
            filteredLight: bestFilteredLightColor,
            observedLight: bestObservedLightColor,
            speedStatus: speedStatus
        )

        if previousObservedLight == .red && bestObservedLightColor == .green {
            detectionState.triggerGreenTransitionCue()
        }
        previousObservedLight = bestObservedLightColor

        detectionState.lightColor = stateManager.displayState

        let chimeFired = stateMachineChime || fallbackChime
        chimeController.isMuted = !detectionState.isChimeEnabled
        if chimeFired {
            chimeController.play()
            detectionState.triggerGreenTransitionCue()
        }

        TelemetryLogger.shared.log(TelemetryEvent(
            filteredLight: bestFilteredLightColor,
            observedLight: bestObservedLightColor,
            speedStatus: speedStatus,
            stateMachineChime: stateMachineChime,
            fallbackChime: fallbackChime,
            displayState: stateManager.displayState
        ))
    }

    private func resolveTrafficLightColor(label: String, box: CGRect) -> DetectedLightColor {
        switch label {
        case "traffic_light_red":
            return .red
        case "traffic_light_green":
            return .green
        case "traffic_light_na":
            return .yellow
        case "traffic light":
            guard let pixelBuffer = currentPixelBuffer else { return .unknown }
            if let modelColor = TrafficLightStateClassifier.shared.classify(
                pixelBuffer: pixelBuffer,
                boundingBox: box
            ), modelColor != .unknown, modelColor != .none {
                return modelColor
            }
            return ColorHeuristic.analyze(pixelBuffer: pixelBuffer, boundingBox: box)
        default:
            return .none
        }
    }

    override func setupAVCapture() {
        super.setupAVCapture()
        setupLayers()
        updateLayerGeometry()
        if let error = setupVision() {
            showModelUnavailableAlert(error)
        }
        startCaptureSession()
    }

    private func setupLayers() {
        detectionOverlay = CALayer()
        detectionOverlay.name = "DetectionOverlay"
        detectionOverlay.bounds = CGRect(origin: .zero, size: bufferSize)
        detectionOverlay.position = CGPoint(x: rootLayer.bounds.midX, y: rootLayer.bounds.midY)
        rootLayer.addSublayer(detectionOverlay)
    }

    private func updateLayerGeometry() {
        let bounds = rootLayer.bounds
        let xScale = bounds.width / bufferSize.width
        let yScale = bounds.height / bufferSize.height
        var scale = max(xScale, yScale)

        if scale.isInfinite { scale = 1.0 }

        CATransaction.begin()
        CATransaction.setValue(kCFBooleanTrue, forKey: kCATransactionDisableActions)
        detectionOverlay.setAffineTransform(CGAffineTransform(rotationAngle: 0).scaledBy(x: scale, y: -scale))
        detectionOverlay.position = CGPoint(x: bounds.midX, y: bounds.midY)
        CATransaction.commit()
    }

    private func drawBox(_ bounds: CGRect, label: String) -> CAShapeLayer {
        let layer = CAShapeLayer()
        layer.bounds = bounds
        layer.position = CGPoint(x: bounds.midX, y: bounds.midY)
        layer.cornerRadius = 4
        layer.borderWidth = 8

        switch label {
        case "traffic_light_red", "stop sign":
            layer.borderColor = Constants.BoxColours.trafficRed
        case "traffic_light_green", "traffic light":
            layer.borderColor = Constants.BoxColours.trafficGreen
        case "traffic_light_na":
            layer.borderColor = Constants.BoxColours.trafficNa
        case "person", "bicycle":
            layer.borderColor = Constants.BoxColours.pedestrian
        default:
            layer.borderColor = Constants.BoxColours.misc
        }

        return layer
    }

    private func drawLabel(_ bounds: CGRect, label: String, confidence: VNConfidence) -> CATextLayer {
        let layer = CATextLayer()
        layer.name = "Object Label"

        let font = UIFont.systemFont(ofSize: 28, weight: .medium)
        let text = String(format: "%@ (%.0f%%)", label, confidence * 100)
        let attributes: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: CGColor(gray: 0.95, alpha: 1.0),
        ]
        layer.string = NSAttributedString(string: text, attributes: attributes)

        let width: CGFloat = CGFloat(text.count) * 13
        layer.bounds = CGRect(x: 0, y: 0, width: width, height: 36)
        layer.position = CGPoint(x: bounds.minX + width / 2, y: bounds.maxY + 18)
        layer.setAffineTransform(CGAffineTransform(scaleX: 1, y: -1))
        return layer
    }

    private func boolDefaultTrue(_ key: String) -> Bool {
        if UserDefaults.standard.object(forKey: key) == nil {
            return true
        }
        return UserDefaults.standard.bool(forKey: key)
    }

    private func showModelUnavailableAlert(_ error: NSError) {
        DispatchQueue.main.async {
            let alert = UIAlertController(
                title: "Model Unavailable",
                message: "Could not load the detection model.\\n\\n\(error.localizedDescription)",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "OK", style: .default))
            self.present(alert, animated: true)
        }
    }
}
