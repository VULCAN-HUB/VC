// 공유 시트에서 VC 로 보내기 (오너 결정 29 · 편의 기능 11번).
//
// ★★ **여기서는 망을 안 탄다.** 받은 것을 앱 그룹 자리(`공유함/`)에 파일로 떨어뜨리고 바로 닫는다.
//   - 열쇠(pair token)를 확장에 안 넘긴다 — 새는 자리를 하나 더 만들지 않는다.
//   - 공유 확장은 기억이 빠듯하고(수십 MB) 언제든 죽는다. 큰 사진을 올리다 죽으면 사람은
//     「보냈다」고 믿는데 아무것도 안 남는다. **받아 적는 데까지만** 하고, 보내는 일은 본 앱의
//     대기함이 한다(못 닿으면 쌓였다가 나중에 간다 — 이미 있는 길이다).
import MobileCoreServices
import UIKit
import UniformTypeIdentifiers

/// 본 앱과 같이 보는 자리. 본 앱의 `SharedInbox` 와 **같은 이름**이어야 한다.
let vcAppGroup = "group.com.unknown8563.vcApp"
let vcInboxDir = "공유함"

class ShareViewController: UIViewController {
    private var 남은것 = 0
    private var 제목 = ""
    private var 줄들: [String] = []
    private var 붙임: [String] = []
    private let 묶음 = UUID().uuidString.prefix(8).lowercased()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.04, green: 0.05, blue: 0.06, alpha: 1)
        보이기("VC 에 넣는 중…")

        let 항목들 = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
        let 딸린것 = 항목들.flatMap { $0.attachments ?? [] }
        제목 = (항목들.first?.attributedContentText?.string ?? "")
            .split(separator: "\n").first.map(String.init) ?? ""
        남은것 = 딸린것.count
        if 남은것 == 0 { 끝내기() ; return }
        for p in 딸린것 { 하나받기(p) }
    }

    private func 하나받기(_ p: NSItemProvider) {
        // 사진·PDF 먼저 본다 — 글도 같이 들어 있는 경우가 많다(사파리 공유가 그렇다).
        if p.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
            p.loadItem(forTypeIdentifier: UTType.image.identifier) { [weak self] item, _ in
                self?.파일로(item, 기본확장자: "jpg")
            }
        } else if p.hasItemConformingToTypeIdentifier(UTType.pdf.identifier) {
            p.loadItem(forTypeIdentifier: UTType.pdf.identifier) { [weak self] item, _ in
                self?.파일로(item, 기본확장자: "pdf")
            }
        } else if p.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            p.loadItem(forTypeIdentifier: UTType.url.identifier) { [weak self] item, _ in
                self?.줄더하기((item as? URL)?.absoluteString ?? "")
            }
        } else if p.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            p.loadItem(forTypeIdentifier: UTType.plainText.identifier) { [weak self] item, _ in
                self?.줄더하기(item as? String ?? "")
            }
        } else {
            줄더하기("")
        }
    }

    private func 파일로(_ item: Any?, 기본확장자: String) {
        var 데이터: Data?
        var 이름 = "공유 \(묶음)-\(붙임.count + 1).\(기본확장자)"
        if let url = item as? URL {
            데이터 = try? Data(contentsOf: url)
            if !url.lastPathComponent.isEmpty { 이름 = url.lastPathComponent }
        } else if let 그림 = item as? UIImage {
            데이터 = 그림.jpegData(compressionQuality: 0.9)
        } else if let d = item as? Data {
            데이터 = d
        }
        if let d = 데이터, let 자리 = 공유자리()?.appendingPathComponent(이름) {
            try? d.write(to: 자리)
            붙임.append(이름)
        }
        하나끝()
    }

    private func 줄더하기(_ 글: String) {
        let 다듬 = 글.trimmingCharacters(in: .whitespacesAndNewlines)
        if !다듬.isEmpty { 줄들.append(다듬) }
        하나끝()
    }

    private func 하나끝() {
        남은것 -= 1
        if 남은것 <= 0 { DispatchQueue.main.async { self.끝내기() } }
    }

    /// 앱 그룹 안 `공유함/` — 본 앱이 켜질 때 여기를 훑는다.
    private func 공유자리() -> URL? {
        guard let 뿌리 = FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: vcAppGroup) else { return nil }
        let 자리 = 뿌리.appendingPathComponent(vcInboxDir)
        try? FileManager.default.createDirectory(at: 자리, withIntermediateDirectories: true)
        return 자리
    }

    private func 끝내기() {
        let 몸 = 줄들.joined(separator: "\n\n")
        if 몸.isEmpty && 붙임.isEmpty {
            보이기("보낼 것이 없어")
        } else if let 자리 = 공유자리() {
            let 쪽지: [String: Any] = [
                "id": "share-\(묶음)",
                "title": 제목.count > 40 ? String(제목.prefix(40)) : 제목,
                "text": 몸,
                "files": 붙임,
                "when": ISO8601DateFormatter().string(from: Date()),
            ]
            if let d = try? JSONSerialization.data(withJSONObject: 쪽지) {
                try? d.write(to: 자리.appendingPathComponent("\(묶음).json"))
            }
            보이기(붙임.isEmpty ? "VC 에 넣었어" : "VC 에 넣었어 · 📎\(붙임.count)")
        } else {
            // 앱 그룹이 없으면 **조용히 삼키지 않는다** — 사람이 보냈다고 믿으면 안 된다.
            보이기("VC 가 이 폰에 안 깔렸거나 권한이 없어")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
            self.extensionContext?.completeRequest(returningItems: nil)
        }
    }

    private func 보이기(_ 말: String) {
        view.subviews.forEach { $0.removeFromSuperview() }
        let 글 = UILabel()
        글.text = 말
        글.textColor = UIColor(red: 1, green: 0.35, blue: 0.2, alpha: 1)
        글.font = .systemFont(ofSize: 17, weight: .semibold)
        글.textAlignment = .center
        글.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(글)
        NSLayoutConstraint.activate([
            글.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            글.centerYAnchor.constraint(equalTo: view.centerYAnchor),
        ])
    }
}
