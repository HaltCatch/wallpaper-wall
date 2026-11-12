package local.wallpaperwall.android

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Launcher / info screen. The actual wallpaper setting happens in
 * [SetWallpaperActivity], which the web preview opens directly via a
 * `wallpaperwall://set` deep link and which applies the wallpaper in the
 * background. This screen only explains how to use the helper for anyone who
 * opens the app from the launcher.
 */
class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(36, 96, 36, 36)
            addView(TextView(context).apply { text = "Wallpaper Wall"; textSize = 26f })
            addView(TextView(context).apply {
                text = "在浏览器打开壁纸墙，进入某张壁纸预览后点击“设为壁纸”，" +
                    "选择桌面 / 锁屏 / 两者即可。本助手会在后台完成设置并弹出结果提示，" +
                    "无需在此界面操作。"
                textSize = 15f
                setPadding(0, 28, 0, 0)
                setLineSpacing(8f, 1f)
            })
        }
        setContentView(content)
    }
}
