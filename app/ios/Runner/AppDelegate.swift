import Flutter
import UIKit
import Vision

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    // 사진 속 글자 — 기기 안 글자 인식(Apple Vision). 밖으로 안 나간다(편의 기능 13번).
    if let reg = engineBridge.pluginRegistry.registrar(forPlugin: "VcText") {
      let channel = FlutterMethodChannel(name: "vc/text", binaryMessenger: reg.messenger())
      channel.setMethodCallHandler { call, result in
        guard call.method == "read", let path = call.arguments as? String else {
          result(FlutterMethodNotImplemented)
          return
        }
        DispatchQueue.global(qos: .userInitiated).async {
          let text = AppDelegate.readText(path)
          DispatchQueue.main.async { result(text) }
        }
      }
    }
    // 공유 시트로 들어온 것이 쌓이는 자리를 알려 준다(결정 29 · 편의 기능 11번).
    //   확장은 거기에 파일만 떨어뜨리고, 보내는 일은 앱의 대기함이 한다.
    if let reg = engineBridge.pluginRegistry.registrar(forPlugin: "VcShare") {
      let channel = FlutterMethodChannel(name: "vc/share", binaryMessenger: reg.messenger())
      channel.setMethodCallHandler { call, result in
        guard call.method == "dir" else {
          result(FlutterMethodNotImplemented)
          return
        }
        guard let root = FileManager.default
          .containerURL(forSecurityApplicationGroupIdentifier: "group.com.unknown8563.vcApp") else {
          // 앱 그룹 권한이 없으면 **조용히 빈 자리를 주지 않는다** — 없는 것과 못 여는 것은 다르다.
          result(FlutterError(code: "no_group", message: "앱 그룹 권한이 없다", details: nil))
          return
        }
        let dir = root.appendingPathComponent("공유함")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        result(dir.path)
      }
    }
  }

  static func readText(_ path: String) -> String {
    guard let image = UIImage(contentsOfFile: path), let cg = image.cgImage else { return "" }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ko-KR", "en-US"]
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cg, orientation: orientation(image.imageOrientation), options: [:])
    do {
      try handler.perform([request])
    } catch {
      return ""
    }
    return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
  }

  static func orientation(_ o: UIImage.Orientation) -> CGImagePropertyOrientation {
    switch o {
    case .up: return .up
    case .down: return .down
    case .left: return .left
    case .right: return .right
    case .upMirrored: return .upMirrored
    case .downMirrored: return .downMirrored
    case .leftMirrored: return .leftMirrored
    case .rightMirrored: return .rightMirrored
    @unknown default: return .up
    }
  }
}
