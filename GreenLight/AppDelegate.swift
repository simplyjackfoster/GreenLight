import SwiftUI

@main
struct GreenLightApp: App {
    @State private var environment = AppEnvironment.live

    var body: some Scene {
        WindowGroup {
            CameraView(viewModel: CameraViewModel(environment: environment))
        }
    }
}
