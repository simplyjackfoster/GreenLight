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
                        VStack(alignment: .trailing) {
                            Text("\(Int(viewModel.speed))").font(.largeTitle)
                            Text(viewModel.speedUnit)
                        }
                        .padding(10)
                        .background(.ultraThinMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    Spacer()
                }
                .padding()
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
