plugins {
    id("com.android.application") version "8.6.1" apply false
    // MainActivity is written in Kotlin; without this plugin AGP silently skips
    // every .kt file and ships an APK that has no activity class at all.
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
