plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// One number for the PC and the phone: the VERSION file at the repo
// root, one line, MAJOR.MINOR.PATCH[-beta.N] (DISTRIBUTION_PLAN.md
// chapter 11, D21). versionCode is derived from it so it can never go
// backwards and never needs a hand: MAJOR*10000 + MINOR*100 + PATCH.
// The last hand-typed versionCode was 12; 1.1.0 reads as 10100.
val deskitVersion = rootProject.file("../VERSION").readText().trim()
val deskitNumbers = deskitVersion.substringBefore("-").split(".").map { it.toInt() }

android {
    namespace = "com.yoav.dictation"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.yoav.dictation"
        // 26 covers every phone still receiving updates; switchToPrevious-
        // InputMethod needs 28 and is guarded at the call site.
        minSdk = 26
        targetSdk = 34
        // Three numbers, his ask (2026-09-13): bump the last for a fix,
        // the middle for something new — in the VERSION file, nowhere
        // else; versionCode follows on its own.
        versionCode = deskitNumbers[0] * 10000 + deskitNumbers[1] * 100 + deskitNumbers[2]
        versionName = deskitVersion
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
