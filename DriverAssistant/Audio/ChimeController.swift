import AVFoundation

final class ChimeController {

    private var player: AVAudioPlayer?
    var isMuted: Bool = false

    init() {
        guard let url = Bundle.main.url(forResource: Constants.Chime.resourceName, withExtension: "aiff")
            ?? Bundle.main.url(forResource: Constants.Chime.resourceName, withExtension: "caf") else {
            print("[ChimeController] Warning: chime sound file not found in bundle")
            return
        }

        do {
            player = try AVAudioPlayer(contentsOf: url)
            player?.prepareToPlay()
        } catch {
            print("[ChimeController] Failed to load chime: \(error)")
        }
    }

    func play() {
        guard !isMuted, let player else { return }
        player.currentTime = 0
        if !player.play() {
            print("[ChimeController] play() returned false; check audio route/session state")
        }
    }
}
