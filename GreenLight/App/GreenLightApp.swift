import SwiftUI

@main
struct GreenLightApp: App {
    @State private var dependencies = AppDependencyContainer.live

    var body: some Scene {
        WindowGroup {
            CameraView(viewModel: CameraViewModel(dependencies: dependencies))
        }
    }
}
