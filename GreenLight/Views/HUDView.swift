import SwiftUI

struct CameraView: View {
    @State var viewModel: CameraViewModel
    @State private var showSettings = false

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Color.black.ignoresSafeArea()

            VStack {
                if viewModel.showGreenAlert {
                    Text("Green light detected")
                        .padding(10)
                        .background(Color.green.opacity(0.9))
                        .clipShape(Capsule())
                } else if viewModel.showLensSmudgeWarning {
                    Text("Lens smudge detected")
                        .padding(10)
                        .background(Color.orange.opacity(0.9))
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
