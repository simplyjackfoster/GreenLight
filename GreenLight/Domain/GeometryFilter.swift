import CoreGraphics

struct GeometryFilter {
    static func passes(
        normalizedBox: CGRect,
        minimumAreaFraction: CGFloat = Constants.Detection.minimumAreaFraction,
        topFraction: CGFloat = Constants.Detection.topFraction,
        centerFraction: CGFloat = Constants.Detection.centerFraction
    ) -> Bool {
        let area = normalizedBox.width * normalizedBox.height
        guard area >= minimumAreaFraction else { return false }
        let midY = normalizedBox.midY
        let minimumY = 1.0 - topFraction
        guard midY >= minimumY else { return false }
        let midX = normalizedBox.midX
        let margin = (1.0 - centerFraction) / 2.0
        return midX >= margin && midX <= (1.0 - margin)
    }
}
