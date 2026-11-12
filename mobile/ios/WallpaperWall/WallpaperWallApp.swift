import SwiftUI
import Photos
import UIKit

@main
struct WallpaperWallApp: App {
    @State private var message = "从 Wallpaper Wall 点击“设为壁纸”后，图片会保存到照片。"

    var body: some Scene {
        WindowGroup {
            VStack(spacing: 18) {
                Text("Wallpaper Wall").font(.largeTitle)
                Text(message).multilineTextAlignment(.center).foregroundStyle(.secondary)
            }
            .padding(32)
            .onOpenURL { url in receive(url) }
        }
    }

    @MainActor private func receive(_ url: URL) {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let raw = components.queryItems?.first(where: { $0.name == "source" })?.value,
              let imageURL = URL(string: raw) else {
            message = "链接中没有可下载的图片。"
            return
        }
        message = "正在下载并保存到照片…"
        Task {
            do {
                let (data, _) = try await URLSession.shared.data(from: imageURL)
                guard let image = UIImage(data: data) else { throw URLError(.cannotDecodeContentData) }
                try await PHPhotoLibrary.shared().performChanges {
                    PHAssetChangeRequest.creationRequestForAsset(from: image)
                }
                message = "已保存到照片。请在照片中使用“设为墙纸”完成系统确认。"
            } catch {
                message = "保存失败：\(error.localizedDescription)"
            }
        }
    }
}
