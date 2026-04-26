import SwiftUI

struct HUDView: View {

    @ObservedObject private var state = DetectionState.shared
    @State private var showSettings = false
    @AppStorage("showSpeed") private var showSpeed = true

    var body: some View {
        ZStack {
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture {
                    withAnimation {
                        showSettings.toggle()
                    }
                }

            VStack {
                if showSpeed {
                    HStack {
                        Spacer()
                        VStack(spacing: 0) {
                            Text("\(Int(state.speed))")
                                .font(.system(size: 80, weight: .regular, design: .rounded))
                                .foregroundColor(.white)
                            Text(state.speedUnit)
                                .font(.system(size: 36, weight: .light))
                                .foregroundColor(.white.opacity(0.85))
                        }
                        .padding(.top, 60)
                        .padding(.trailing, 20)
                    }
                }

                Spacer()

                if showSettings {
                    NavigationLink(destination: SettingsView()) {
                        Label("Settings", systemImage: "gearshape.fill")
                            .font(.body)
                            .foregroundColor(.white)
                            .padding(.horizontal, 20)
                            .padding(.vertical, 10)
                            .background(Color.black.opacity(0.45))
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    .padding(.bottom, 40)
                    .transition(.opacity)
                }
            }
        }
        .navigationBarHidden(true)
    }
}
