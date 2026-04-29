import SwiftUI
import UIKit
import AVFoundation

struct CameraView: View {
    @State var viewModel: CameraViewModel
    @State private var showSettings = false

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            CameraPreview(session: viewModel.camera.previewSession)
                .ignoresSafeArea()

            if viewModel.settings.showBoundingBoxes {
                GeometryReader { proxy in
                    ZStack(alignment: .topLeading) {
                        ForEach(Array(viewModel.boundingBoxes.enumerated()), id: \.offset) { _, box in
                            let rect = denormalize(box.rect, in: proxy.size)
                            Rectangle()
                                .stroke(Color.green, lineWidth: 2)
                                .frame(width: max(2, rect.width), height: max(2, rect.height))
                                .position(x: rect.midX, y: rect.midY)

                            if viewModel.settings.showLabels {
                                Text(labelText(for: box))
                                    .font(.caption2.weight(.semibold))
                                    .lineLimit(1)
                                    .fixedSize(horizontal: true, vertical: true)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 3)
                                    .background(Color.black.opacity(0.75), in: Capsule())
                                    .foregroundStyle(.white)
                                    .offset(
                                        x: labelX(for: rect, in: proxy.size),
                                        y: labelY(for: rect, in: proxy.size)
                                    )
                            }
                        }
                    }
                }
                .allowsHitTesting(false)
            }

            VStack {
                if viewModel.showGreenAlert {
                    Text("Green light detected")
                        .padding(10)
                        .background(Color.green.opacity(0.9))
                        .clipShape(Capsule())
                }
                Spacer()
            }
            .padding(.top, 24)

            if viewModel.settings.showSpeed {
                VStack {
                    HStack {
                        Spacer()
                        SpeedPanel(
                            speed: viewModel.speed,
                            speedUnit: viewModel.speedUnit,
                            speedStatus: viewModel.speedStatus
                        )
                    }
                    Spacer()
                }
                .padding(.horizontal)
                .padding(.top, 12)
            }

            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .padding(12)
                    .background(.ultraThinMaterial)
                    .clipShape(Circle())
            }
            .padding()
        }
        .sheet(isPresented: $showSettings) { SettingsView(settings: viewModel.settings) }
        .task { viewModel.start() }
    }

    private func denormalize(_ rect: CGRect, in size: CGSize) -> CGRect {
        let x = rect.minX * size.width
        let y = (1.0 - rect.maxY) * size.height
        let width = rect.width * size.width
        let height = rect.height * size.height
        return CGRect(x: x, y: y, width: width, height: height)
    }

    private func labelText(for box: BoundingBox) -> String {
        let normalized = box.label
            .lowercased()
            .replacingOccurrences(of: "_", with: " ")

        let shortLabel: String
        if normalized.contains("red") {
            shortLabel = "Red"
        } else if normalized.contains("green") {
            shortLabel = "Green"
        } else if normalized.contains("yellow") || normalized.contains("amber") || normalized.contains(" na") {
            shortLabel = "Yellow"
        } else if normalized.contains("traffic"), normalized.contains("light") {
            shortLabel = "Traffic light"
        } else {
            shortLabel = box.label
        }

        return "\(shortLabel) \(Int(box.confidence * 100))%"
    }

    private func labelX(for rect: CGRect, in size: CGSize) -> CGFloat {
        let estimatedLabelWidth: CGFloat = 150
        return min(max(0, rect.minX), max(0, size.width - estimatedLabelWidth))
    }

    private func labelY(for rect: CGRect, in size: CGSize) -> CGFloat {
        let labelHeight: CGFloat = 22
        let above = rect.minY - labelHeight
        if above >= 0 {
            return above
        }
        return min(rect.maxY + 6, max(0, size.height - labelHeight))
    }
}

private struct SpeedPanel: View {
    let speed: Double
    let speedUnit: String
    let speedStatus: SpeedStatus

    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("\(Int(speed))")
                    .font(.system(size: 44, weight: .bold, design: .rounded))
                    .monospacedDigit()
                Text(speedUnit.uppercased())
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            Text(statusText)
                .font(.caption2.weight(.semibold))
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(statusTint.opacity(0.2), in: Capsule())
                .foregroundStyle(statusTint)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(.ultraThinMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(.white.opacity(0.25), lineWidth: 1)
        )
    }

    private var statusText: String {
        switch speedStatus {
        case .knownStationary:
            return "Stopped"
        case .knownMoving:
            return "Moving"
        case .unknown:
            return "Speed Unknown"
        }
    }

    private var statusTint: Color {
        switch speedStatus {
        case .knownStationary:
            return .green
        case .knownMoving:
            return .orange
        case .unknown:
            return .gray
        }
    }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.videoPreviewLayer.videoGravity = .resizeAspectFill
        view.videoPreviewLayer.session = session
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        uiView.videoPreviewLayer.session = session
    }
}

final class PreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

    var videoPreviewLayer: AVCaptureVideoPreviewLayer {
        guard let layer = layer as? AVCaptureVideoPreviewLayer else {
            return AVCaptureVideoPreviewLayer()
        }
        return layer
    }
}
