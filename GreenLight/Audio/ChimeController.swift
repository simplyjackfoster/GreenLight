import AVFoundation

actor AudioService: AudioServiceProtocol {
    private var player: AVAudioPlayer?
    private(set) var isMuted = false

    init() {
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [.duckOthers])
            try AVAudioSession.sharedInstance().setActive(true)
        } catch {}

        guard let url = Bundle.main.url(forResource: Constants.Chime.resourceName, withExtension: "aiff") else { return }
        player = try? AVAudioPlayer(contentsOf: url)
        player?.prepareToPlay()
    }

    func setMuted(_ muted: Bool) { isMuted = muted }

    nonisolated func play() {
        Task {
            await _play()
        }
    }

    private func _play() {
        guard !isMuted, let player else { return }
        player.currentTime = 0
        _ = player.play()
    }
}
