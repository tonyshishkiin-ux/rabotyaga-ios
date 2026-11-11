import SwiftUI

private struct Opportunity: Identifiable {
    let id: String
    let title: String
    let budget: String
    let source: String
    let description: String
    let reason: String
    let tags: [String]

    static let examples: [Opportunity] = [
        Opportunity(id: "demo-telegram", title: "Telegram-бот для записи клиентов", budget: "от 45 000 ₽", source: "Демонстрационный заказ", description: "Нужны запись на услуги, уведомления администратору и простая панель управления.", reason: "Совпадает со специализацией: Telegram-боты и интеграции.", tags: ["Telegram", "Python", "Интеграции"]),
        Opportunity(id: "demo-miniapp", title: "Mini App с каталогом и оплатой", budget: "от 90 000 ₽", source: "Демонстрационный заказ", description: "Разработать интерфейс каталога и связать его с ботом и существующей CRM.", reason: "Подходит по навыкам Mini Apps, сайтов и автоматизации.", tags: ["Mini App", "CRM", "API"]),
        Opportunity(id: "demo-ai", title: "ИИ-ассистент для обработки заявок", budget: "от 75 000 ₽", source: "Демонстрационный заказ", description: "Классифицировать обращения, готовить черновики ответов и передавать их менеджеру на подтверждение.", reason: "Прямая задача по разработке ИИ-агентов.", tags: ["ИИ-агент", "Python", "Автоматизация"])
    ]
}

private enum OpportunityDecision: String, Codable {
    case passed
    case interested
    case saved
}

private enum AppTab: String {
    case chat
    case opportunities
    case tasks
    case settings
}

struct ContentView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AppStorage("shabashka.decisions.v1") private var decisionsJSON = "{}"
    @SceneStorage("selectedTab.v1") private var selectedTab = AppTab.chat.rawValue
    @State private var selectedOpportunity: Opportunity?
    @StateObject private var chatStore = ChatStore()

    private var decisions: [String: OpportunityDecision] {
        guard let data = decisionsJSON.data(using: .utf8),
              let decoded = try? JSONDecoder().decode([String: OpportunityDecision].self, from: data) else {
            return [:]
        }
        return decoded
    }

    private var nextOpportunity: Opportunity? {
        Opportunity.examples.first { decisions[$0.id] == nil }
    }

    private var interested: [Opportunity] {
        Opportunity.examples.filter { decisions[$0.id] == .interested }
    }

    private var saved: [Opportunity] {
        Opportunity.examples.filter { decisions[$0.id] == .saved }
    }

    private func decide(_ decision: OpportunityDecision, for opportunity: Opportunity) {
        var updated = decisions
        updated[opportunity.id] = decision
        guard let encoded = try? JSONEncoder().encode(updated),
              let text = String(data: encoded, encoding: .utf8) else { return }
        withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) {
            decisionsJSON = text
        }
    }

    private func resetDecisions() {
        withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) {
            decisionsJSON = "{}"
        }
    }

    private func handleSwipe(_ value: DragGesture.Value, for opportunity: Opportunity) {
        let horizontalDistance = value.translation.width
        let verticalDistance = value.translation.height

        guard abs(horizontalDistance) > 90,
              abs(horizontalDistance) > abs(verticalDistance) * 1.25 else {
            return
        }

        decide(horizontalDistance > 0 ? .interested : .passed, for: opportunity)
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            chatTab
                .tabItem { Label("Чат", systemImage: "message.fill") }
                .tag(AppTab.chat.rawValue)

            opportunitiesTab
                .tabItem { Label("Шабашка", systemImage: "briefcase.fill") }
                .tag(AppTab.opportunities.rawValue)

            tasksTab
                .tabItem { Label("Задачи", systemImage: "checklist") }
                .tag(AppTab.tasks.rawValue)

            settingsTab
                .tabItem { Label("Настройки", systemImage: "gearshape.fill") }
                .tag(AppTab.settings.rawValue)
        }
        .tint(Color.accentColor)
        .preferredColorScheme(.dark)
        .sheet(item: $selectedOpportunity) { opportunity in
            opportunityDetails(opportunity)
        }
    }

    private var chatTab: some View {
        HermesChatView(store: chatStore) {
            selectedTab = AppTab.settings.rawValue
        }
    }

    private var opportunitiesTab: some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Шабашка")
                            .font(.largeTitle.bold())
                        Text("Демонстрационные заказы. Реальный поиск подключим к Hermes.")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                    }

                    if let opportunity = nextOpportunity {
                        opportunityCard(opportunity)
                            .simultaneousGesture(
                                DragGesture(minimumDistance: 40)
                                    .onEnded { value in
                                        handleSwipe(value, for: opportunity)
                                    }
                            )
                            .accessibilityHint("Свайп вправо: интересно. Влево: пропустить.")
                            .accessibilityAction(named: Text("Отметить как интересно")) {
                                decide(.interested, for: opportunity)
                            }
                            .accessibilityAction(named: Text("Пропустить заказ")) {
                                decide(.passed, for: opportunity)
                            }
                        HStack(spacing: 12) {
                            decisionButton("Пропустить", icon: "xmark", color: .red) {
                                decide(.passed, for: opportunity)
                            }
                            decisionButton("Сохранить", icon: "bookmark.fill", color: Color.accentColor) {
                                decide(.saved, for: opportunity)
                            }
                            decisionButton("Интересно", icon: "heart.fill", color: .green) {
                                decide(.interested, for: opportunity)
                            }
                        }
                        .frame(maxWidth: .infinity)
                    } else {
                        VStack(spacing: 16) {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 48))
                                .foregroundColor(.green)
                            Text("Все карточки просмотрены")
                                .font(.title2.bold())
                            Text("В разделе «Задачи» сохранены интересные предложения.")
                                .foregroundColor(.secondary)
                                .multilineTextAlignment(.center)
                            Button("Начать демонстрацию заново") {
                                resetDecisions()
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(Color.accentColor)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 56)
                    }
                    Text("Свайп вправо готовит заказ к рассмотрению, но никогда не отправляет отклик автоматически.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
                .padding(20)
            }
            .navigationBarHidden(true)
        }
        .navigationViewStyle(.stack)
    }

    private func opportunityCard(_ opportunity: Opportunity) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Label("Подходит по специализации", systemImage: "checkmark.seal.fill")
                    .font(.footnote.weight(.semibold))
                    .foregroundColor(.green)
                Spacer(minLength: 0)
                Text("ДЕМО")
                    .font(.footnote.bold())
                    .foregroundColor(.secondary)
            }
            Text(opportunity.title)
                .font(.title2.bold())
                .fixedSize(horizontal: false, vertical: true)
            Text(opportunity.budget)
                .font(.title.bold())
                .foregroundColor(Color.accentColor)
            Text(opportunity.description)
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)
            Text("Почему Работяга рекомендует")
                .font(.subheadline.bold())
            Text(opportunity.reason)
                .font(.subheadline)
                .foregroundColor(.secondary)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(opportunity.tags, id: \.self) { tag in
                        Text(tag)
                            .font(.footnote)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                            .background(Color.secondary.opacity(0.16), in: Capsule())
                    }
                }
            }
            Button("Подробнее") {
                selectedOpportunity = opportunity
            }
            .frame(maxWidth: .infinity)
            .buttonStyle(.bordered)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 20))
    }

    private func decisionButton(_ title: String, icon: String, color: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.title2.bold())
                    .frame(width: 56, height: 56)
                    .background(color.opacity(0.16), in: Circle())
                Text(title)
                    .font(.footnote)
            }
            .foregroundColor(color)
        }
        .buttonStyle(.plain)
        .frame(minWidth: 76, minHeight: 88)
        .accessibilityLabel(title)
        .accessibilityHint(decisionHint(for: title))
    }

    private func decisionHint(for title: String) -> String {
        switch title {
        case "Пропустить":
            return "Убирает карточку из текущей демонстрации"
        case "Сохранить":
            return "Добавляет заказ в раздел Задачи, Отложено"
        default:
            return "Добавляет заказ в раздел Задачи, Интересно"
        }
    }

    private func opportunityDetails(_ opportunity: Opportunity) -> some View {
        NavigationView {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(opportunity.title)
                        .font(.title.bold())
                    Text(opportunity.budget)
                        .font(.title2.weight(.semibold))
                        .foregroundColor(Color.accentColor)
                    Text(opportunity.description)
                    Text("Оценка Работяги")
                        .font(.headline)
                    Text(opportunity.reason)
                        .foregroundColor(.secondary)
                    Text("Источник: \(opportunity.source)")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                    Text("После подключения Hermes здесь появятся ссылка на реальный заказ и черновик отклика. Отправка возможна только после отдельного подтверждения.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(20)
            }
            .navigationTitle("Заказ")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Закрыть") { selectedOpportunity = nil }
                }
            }
        }
        .navigationViewStyle(.stack)
    }

    private var tasksTab: some View {
        NavigationView {
            List {
                Section("Интересно · \(interested.count)") {
                    if interested.isEmpty {
                        Text("Пока нет выбранных заказов")
                            .foregroundColor(.secondary)
                    }
                    ForEach(interested) { opportunity in
                        Button {
                            selectedOpportunity = opportunity
                        } label: {
                            opportunityRow(opportunity)
                        }
                        .accessibilityHint("Открывает подробности заказа")
                    }
                }
                Section("Отложено · \(saved.count)") {
                    if saved.isEmpty {
                        Text("Пока ничего не отложено")
                            .foregroundColor(.secondary)
                    }
                    ForEach(saved) { opportunity in
                        Button {
                            selectedOpportunity = opportunity
                        } label: {
                            opportunityRow(opportunity)
                        }
                        .accessibilityHint("Открывает подробности заказа")
                    }
                }
                Section {
                    Text("Это локальный список решений по демонстрационным заказам. Реальные задачи Hermes ещё не синхронизируются.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
            }
            .navigationTitle("Задачи")
        }
        .navigationViewStyle(.stack)
    }

    private func opportunityRow(_ opportunity: Opportunity) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(opportunity.title)
                .foregroundColor(.primary)
            Text(opportunity.budget)
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
    }

    private var settingsTab: some View {
        ConnectionSettingsView(store: chatStore)
    }
}
