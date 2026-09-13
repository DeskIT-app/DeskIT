plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.yoav.dictation"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.yoav.dictation"
        // 26 covers every phone still receiving updates; switchToPrevious-
        // InputMethod needs 28 and is guarded at the call site.
        minSdk = 26
        targetSdk = 34
        // Three numbers from here on, his ask (2026-09-13): the next
        // build is 1.1.1, not 1.11 — bump the last for a fix, the middle
        // for something new, and versionCode by one every time.
        versionCode = 12
        versionName = "1.1.0"
    }

    buildTypes {
        release {
            // Unsigned release builds cannot be installed, and a debug
            // build is the only thing sideloadable without a keystore.
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies { }
