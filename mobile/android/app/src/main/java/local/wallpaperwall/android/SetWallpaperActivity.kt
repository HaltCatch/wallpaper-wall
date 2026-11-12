package local.wallpaperwall.android

import android.app.Activity
import android.app.AlertDialog
import android.app.WallpaperManager
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import java.io.FilterInputStream
import java.io.IOException
import java.io.InputStream
import java.net.URL
import java.util.concurrent.Executors

/**
 * Invisible trampoline for `wallpaperwall://set` deep links.
 *
 * The web preview now picks the target (home / lock / both) and passes it as a
 * `target` query parameter, so this activity applies the wallpaper straight away
 * and finishes — the user stays on the browser and only sees a success/failure
 * toast. Its theme is translucent (see AndroidManifest), so there is no visible
 * app switch. Links without a target (older bookmarks) fall back to a small
 * chooser dialog so nothing regresses.
 */
class SetWallpaperActivity : Activity() {
    private companion object { const val MAX_IMAGE_BYTES = 100L * 1024L * 1024L }
    private val worker = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent) {
        val source = intent.data?.getQueryParameter("source")
        if (source.isNullOrBlank()) {
            toast("请从 Wallpaper Wall 的“设为壁纸”按钮打开。")
            finish()
            return
        }
        when (val flags = targetFlags(intent.data?.getQueryParameter("target"))) {
            null -> promptTarget(source)
            else -> apply(source, flags)
        }
    }

    /** Map the web's target token to WallpaperManager flags; null means unset. */
    private fun targetFlags(target: String?): Int? = when (target) {
        "home" -> WallpaperManager.FLAG_SYSTEM
        "lock" -> WallpaperManager.FLAG_LOCK
        "both" -> WallpaperManager.FLAG_SYSTEM or WallpaperManager.FLAG_LOCK
        else -> null
    }

    /** Fallback picker for legacy links that carry no target. */
    private fun promptTarget(source: String) {
        val labels = arrayOf("设为桌面壁纸", "设为锁屏壁纸", "同时设置")
        val flags = intArrayOf(
            WallpaperManager.FLAG_SYSTEM,
            WallpaperManager.FLAG_LOCK,
            WallpaperManager.FLAG_SYSTEM or WallpaperManager.FLAG_LOCK,
        )
        AlertDialog.Builder(this)
            .setTitle("设为壁纸")
            .setItems(labels) { _, index -> apply(source, flags[index]) }
            .setOnCancelListener { finish() }
            .show()
    }

    private fun apply(imageUrl: String, target: Int) {
        worker.execute {
            try {
                val sourceUrl = validateSource(imageUrl)
                val connection = sourceUrl.openConnection().apply {
                    connectTimeout = 10_000
                    readTimeout = 120_000
                    useCaches = false
                }
                if (connection.contentLengthLong > MAX_IMAGE_BYTES) throw IOException("图片超过 100 MB 限制")
                connection.getInputStream().use { stream ->
                    BoundedInputStream(stream, MAX_IMAGE_BYTES).use { bounded ->
                        WallpaperManager.getInstance(applicationContext).setStream(bounded, null, true, target)
                    }
                }
                finishWith("壁纸已设置", Toast.LENGTH_SHORT)
            } catch (error: Exception) {
                finishWith("设置失败：${error.message}", Toast.LENGTH_LONG)
            }
        }
    }

    /** Report the outcome and close. Uses the application context so the toast
     * survives the activity finishing immediately afterwards. */
    private fun finishWith(message: String, length: Int) = runOnUiThread {
        Toast.makeText(applicationContext, message, length).show()
        finish()
    }

    private fun toast(message: String) {
        Toast.makeText(applicationContext, message, Toast.LENGTH_LONG).show()
    }

    private fun validateSource(value: String): URL {
        val url = URL(value)
        require(url.protocol == "https" || (url.protocol == "http" && isLocalHost(url.host))) {
            "非局域网图片必须使用 HTTPS"
        }
        require(url.path.substringAfterLast('.', "").lowercase() in setOf("jpg", "jpeg", "png", "webp", "bmp", "avif")) {
            "图片链接必须使用受支持的图片扩展名"
        }
        return url
    }

    private fun isLocalHost(host: String): Boolean {
        if (host == "localhost" || host == "::1" || host == "[::1]") return true
        // Prefix checks are spoofable: "10.evil.com" is a registrable public DNS
        // name. Only a full literal IPv4 address qualifies as local.
        val octets = host.split('.').map { it.toIntOrNull() }
        if (octets.size != 4 || octets.any { it == null || it !in 0..255 }) return false
        val (first, second) = octets.map { it!! }
        return first == 127 || first == 10 || (first == 192 && second == 168) || (first == 172 && second in 16..31)
    }

    private class BoundedInputStream(source: InputStream, private val maxBytes: Long) : FilterInputStream(source) {
        private var bytesRead = 0L
        private fun count(read: Int): Int {
            if (read > 0) {
                bytesRead += read
                if (bytesRead > maxBytes) throw IOException("图片超过 100 MB 限制")
            }
            return read
        }
        override fun read(): Int {
            val value = super.read()
            if (value >= 0) count(1)
            return value
        }
        override fun read(buffer: ByteArray, offset: Int, length: Int): Int = count(super.read(buffer, offset, length))
    }
}
