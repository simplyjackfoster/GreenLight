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

    @discardableResult
    func setupVision() -> NSError? {
        guard let modelURL = Bundle.main.url(forResource: "yolov5sTraffic", withExtension: "mlmodelc")
            ?? Bundle.main.url(forResource: "yolov8nTraffic", withExtension: "mlpackage") else {
            return NSError(
                domain: "ViewControllerDetection",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "ML model not found"]
            )
        }

        do {
            let mlModel = try MLModel(contentsOf: modelURL)
            let visionModel = try VNCoreMLModel(for: mlModel)
            let request = VNCoreMLRequest(model: visionModel) { [weak self] request, _ in
                guard let self, let results = request.results else { return }
                DispatchQueue.main.async {
                    self.handleResults(results)
                }
            }
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
        var bestLightColor: DetectedLightColor = .none
        var bestConfidence: Float = 0

        for observation in results.compactMap({ $0 as? VNRecognizedObjectObservation }) {
            guard let top = observation.labels.first,
                  Double(top.confidence) >= threshold else { continue }

            let label = top.identifier
            let box = observation.boundingBox

            let lightColor = resolveTrafficLightColor(label: label, box: box)
            if lightColor != .unknown,
               lightColor != .none,
               GeometryFilter.passes(normalizedBox: box),
               top.confidence > bestConfidence {
                bestLightColor = lightColor
                bestConfidence = top.confidence
            }

            let objectBounds = VNImageRectForNormalizedRect(box, Int(bufferSize.width), Int(bufferSize.height))

            if UserDefaults.standard.bool(forKey: "visualizeDetections") {
                detectionOverlay.addSublayer(drawBox(objectBounds, label: label))
            }
            if UserDefaults.standard.bool(forKey: "showLabels") {
                detectionOverlay.addSublayer(drawLabel(objectBounds, label: label, confidence: top.confidence))
            }
        }

        let shouldChime = stateManager.update(
            detectedLight: bestLightColor,
            isStationary: detectionState.isStationary
        )

        detectionState.lightColor = stateManager.displayState

        chimeController.isMuted = !detectionState.isChimeEnabled
        if shouldChime {
            chimeController.play()
        }
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
            return ColorHeuristic.analyze(pixelBuffer: pixelBuffer, boundingBox: box)
        default:
            return .none
        }
    }

    override func setupAVCapture() {
        super.setupAVCapture()
        setupLayers()
        updateLayerGeometry()
        _ = setupVision()
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
}
