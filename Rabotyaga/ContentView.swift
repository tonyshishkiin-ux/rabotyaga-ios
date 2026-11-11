import SwiftUI

struct ContentView: View {
    @State private var statusMessage: String?

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0"
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.black, Color(red: 0.04, green: 0.08, blue: 0.12)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            VStack(spacing: 28) {
                Image(systemName: "bolt.fill")
                    .font(.system(size: 38, weight: .bold))
                    .foregroundStyle(Color.cyan)
                    .accessibilityHidden(true)

                Text("Привет, начальник!")
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                    .multilineTextAlignment(.center)

                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        statusMessage = "Первое приложение работает"
                    }
                } label: {
                    Text("Проверить Работягу")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 15)
                }
                .buttonStyle(.borderedProminent)
                .tint(Color.orange)
                .accessibilityHint("Показывает результат проверки приложения")

                if let statusMessage {
                    Label(statusMessage, systemImage: "checkmark.circle.fill")
                        .font(.headline)
                        .foregroundStyle(Color.green)
                        .transition(.opacity.combined(with: .scale))
                }

                Spacer()

                Text("Версия \(appVersion)")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 44)
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
            .preferredColorScheme(.dark)
    }
}


