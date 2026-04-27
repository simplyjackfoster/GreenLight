import AVFoundation
import SwiftUI
import UIKit
import Vision

class ViewController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {

    private var hudHostController: UIHostingController<HUDView>?

    @IBOutlet weak var trafficLightRed: UIImageView!
    @IBOutlet weak var trafficLightGreen: UIImageView!
    @IBOutlet weak var stopSign: UIImageView!
    @IBOutlet weak private var previewView: UIView!

    var bufferSize: CGSize = .zero
    var rootLayer: CALayer!

    let session = AVCaptureSession()
    private var previewLayer: AVCaptureVideoPreviewLayer!
    let videoDataOutput = AVCaptureVideoDataOutput()
    let videoDataOutputQueue = DispatchQueue(
        label: "com.driverassistant.VideoDataOutput",
        qos: .userInitiated,
        attributes: [],
        autoreleaseFrequency: .workItem
    )

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {}

    override func viewDidLoad() {
        UIApplication.shared.isIdleTimerDisabled = true
        super.viewDidLoad()
        trafficLightRed?.isHidden = true
        trafficLightGreen?.isHidden = true
        stopSign?.isHidden = true

#if targetEnvironment(simulator)
        setupSimulatorPlaceholder()
        return
#else
        setupAVCapture()
#endif
    }

    func setupAVCapture() {
        let discovery = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInWideAngleCamera],
            mediaType: .video,
            position: .back
        )

        guard let videoDevice = discovery.devices.first else {
            showCameraUnavailableAlert()
            return
        }

        let deviceInput: AVCaptureDeviceInput
        do {
            deviceInput = try AVCaptureDeviceInput(device: videoDevice)
        } catch {
            showCameraUnavailableAlert()
            return
        }

        session.beginConfiguration()
        session.sessionPreset = .hd1280x720

        guard session.canAddInput(deviceInput) else {
            session.commitConfiguration()
            return
        }
        session.addInput(deviceInput)

        guard session.canAddOutput(videoDataOutput) else {
            session.commitConfiguration()
            return
        }
        session.addOutput(videoDataOutput)

        videoDataOutput.alwaysDiscardsLateVideoFrames = true
        videoDataOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_420YpCbCr8BiPlanarFullRange)
        ]
        videoDataOutput.setSampleBufferDelegate(self, queue: videoDataOutputQueue)

        do {
            try videoDevice.lockForConfiguration()
            videoDevice.activeVideoMinFrameDuration = CMTime(value: 1, timescale: 15)
            videoDevice.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: 15)
            let dimensions = CMVideoFormatDescriptionGetDimensions(videoDevice.activeFormat.formatDescription)
            bufferSize.width = CGFloat(dimensions.height)
            bufferSize.height = CGFloat(dimensions.width)
            videoDevice.unlockForConfiguration()
        } catch {
            print("[ViewController] Device configuration failed: \(error)")
        }

        session.commitConfiguration()

        previewLayer = AVCaptureVideoPreviewLayer(session: session)
        previewLayer.videoGravity = .resizeAspectFill
        rootLayer = previewView.layer
        previewLayer.frame = rootLayer.bounds
        rootLayer.addSublayer(previewLayer)

        let hud = UIHostingController(rootView: HUDView())
        hud.view.backgroundColor = .clear
        hud.view.translatesAutoresizingMaskIntoConstraints = false
        addChild(hud)
        view.addSubview(hud.view)
        NSLayoutConstraint.activate([
            hud.view.topAnchor.constraint(equalTo: view.topAnchor),
            hud.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            hud.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            hud.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        hud.didMove(toParent: self)
        hudHostController = hud
    }

    func startCaptureSession() {
        // FIXED: startRunning must not execute on main thread.
        videoDataOutputQueue.async { [weak self] in
            guard let self else { return }
            if !self.session.isRunning {
                self.session.startRunning()
            }
        }
    }

    func teardownAVCapture() {
        previewLayer?.removeFromSuperlayer()
        previewLayer = nil
    }

    func captureOutput(
        _ captureOutput: AVCaptureOutput,
        didDrop didDropSampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        // Frame-drop logging can be enabled during debugging.
    }

    private func showCameraUnavailableAlert() {
        DispatchQueue.main.async {
            let alert = UIAlertController(
                title: "Camera Unavailable",
                message: "GreenLight requires camera access. Please enable it in Settings.",
                preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "Open Settings", style: .default) { _ in
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            })
            alert.addAction(UIAlertAction(title: "OK", style: .cancel))
            self.present(alert, animated: true)
        }
    }

    // FIXED: simulator previously returned early with no camera setup and no fallback UI, causing white screen.
    private func setupSimulatorPlaceholder() {
        view.backgroundColor = .black
        previewView?.backgroundColor = .black

        let container = UIView()
        container.translatesAutoresizingMaskIntoConstraints = false
        container.backgroundColor = UIColor(white: 0.08, alpha: 1)
        container.layer.cornerRadius = 14

        let title = UILabel()
        title.translatesAutoresizingMaskIntoConstraints = false
        title.text = "Simulator Preview"
        title.textColor = .white
        title.font = UIFont.systemFont(ofSize: 24, weight: .semibold)
        title.textAlignment = .center

        let body = UILabel()
        body.translatesAutoresizingMaskIntoConstraints = false
        body.text = "Camera capture is unavailable in iOS Simulator.\nRun this on a physical iPhone to test live detection."
        body.textColor = UIColor(white: 0.85, alpha: 1)
        body.font = UIFont.systemFont(ofSize: 16, weight: .regular)
        body.numberOfLines = 0
        body.textAlignment = .center

        view.addSubview(container)
        container.addSubview(title)
        container.addSubview(body)

        NSLayoutConstraint.activate([
            container.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            container.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            container.centerYAnchor.constraint(equalTo: view.centerYAnchor),

            title.topAnchor.constraint(equalTo: container.topAnchor, constant: 24),
            title.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 16),
            title.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -16),

            body.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 14),
            body.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 16),
            body.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -16),
            body.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -24),
        ])
    }
}
