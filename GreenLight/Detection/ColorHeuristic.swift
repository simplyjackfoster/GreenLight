import CoreGraphics
import CoreVideo
import Foundation

struct ColorHeuristic {

    static func classifyHSV(h: Double, s: Double, v: Double) -> DetectedLightColor {
        let isRed = (h <= 15 || h >= 345) && s > 0.50 && v > 0.30
        let isGreen = (h >= 90 && h <= 150) && s > 0.40 && v > 0.30
        let isYellow = (h >= 25 && h <= 60) && s > 0.50 && v > 0.40

        if isRed { return .red }
        if isGreen { return .green }
        if isYellow { return .yellow }
        return .unknown
    }

    static func analyze(pixelBuffer: CVPixelBuffer, boundingBox: CGRect) -> DetectedLightColor {
        let topThird = CGRect(
            x: boundingBox.origin.x,
            y: boundingBox.maxY - boundingBox.height / 3.0,
            width: boundingBox.width,
            height: boundingBox.height / 3.0
        )

        let bufferWidth = CVPixelBufferGetWidth(pixelBuffer)
        let bufferHeight = CVPixelBufferGetHeight(pixelBuffer)

        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        var votes: [DetectedLightColor: Int] = [:]

        for row in 0..<3 {
            for col in 0..<3 {
                let nx = topThird.origin.x + topThird.width * (CGFloat(col) + 0.5) / 3.0
                let ny = topThird.origin.y + topThird.height * (CGFloat(row) + 0.5) / 3.0

                let px = Int(nx * CGFloat(bufferWidth))
                let py = Int((1.0 - ny) * CGFloat(bufferHeight))

                guard px >= 0, px < bufferWidth, py >= 0, py < bufferHeight else { continue }

                let rgb = sampleRGB(pixelBuffer: pixelBuffer, x: px, y: py)
                let hsv = rgbToHSV(r: rgb.r, g: rgb.g, b: rgb.b)
                let color = classifyHSV(h: hsv.h, s: hsv.s, v: hsv.v)
                votes[color, default: 0] += 1
            }
        }

        let meaningfulVotes = votes.filter { $0.key != .unknown && $0.key != .none }
        return meaningfulVotes.max(by: { $0.value < $1.value })?.key ?? .unknown
    }

    private static func sampleRGB(pixelBuffer: CVPixelBuffer, x: Int, y: Int) -> (r: Double, g: Double, b: Double) {
        guard let yPlane = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0),
              let uvPlane = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 1) else {
            return (0, 0, 0)
        }

        let yStride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)
        let uvStride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 1)

        let yValue = Double(yPlane.load(fromByteOffset: y * yStride + x, as: UInt8.self))
        let uvX = (x / 2) * 2
        let uvY = y / 2
        let cbValue = Double(uvPlane.load(fromByteOffset: uvY * uvStride + uvX, as: UInt8.self))
        let crValue = Double(uvPlane.load(fromByteOffset: uvY * uvStride + uvX + 1, as: UInt8.self))

        let Y = yValue
        let Cb = cbValue - 128
        let Cr = crValue - 128

        let r = max(0, min(255, Y + 1.402 * Cr))
        let g = max(0, min(255, Y - 0.344136 * Cb - 0.714136 * Cr))
        let b = max(0, min(255, Y + 1.772 * Cb))

        return (r / 255.0, g / 255.0, b / 255.0)
    }

    private static func rgbToHSV(r: Double, g: Double, b: Double) -> (h: Double, s: Double, v: Double) {
        let maxC = max(r, g, b)
        let minC = min(r, g, b)
        let delta = maxC - minC

        let v = maxC
        let s = maxC > 0 ? delta / maxC : 0

        var h: Double = 0
        if delta > 0 {
            switch maxC {
            case r:
                h = 60 * (((g - b) / delta).truncatingRemainder(dividingBy: 6))
            case g:
                h = 60 * ((b - r) / delta + 2)
            default:
                h = 60 * ((r - g) / delta + 4)
            }
        }

        if h < 0 { h += 360 }
        return (h, s, v)
    }
}
