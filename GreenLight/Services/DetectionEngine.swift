import Foundation

actor DetectionEngine: DetectionEngineProtocol {

    let results: AsyncStream<DetectionResult>
    private let resultsContinuation: AsyncStream<DetectionResult>.Continuation

    init() {
        var cont: AsyncStream<DetectionResult>.Continuation!
        results = AsyncStream(bufferingPolicy: .bufferingNewest(1)) { cont = $0 }
        resultsContinuation = cont
    }

    func attach(camera: any CameraServiceProtocol) async {
        // TODO: implement inference pipeline
    }
}
