import java.util.Properties

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

// The release keystore (DISTRIBUTION_PLAN.md 12.7): generated once by the
// owner, backed up twice, never in the repo. keystore.properties beside
// this project (gitignored) names it — storeFile, storePassword,
// keyAlias, keyPassword — and CI writes the same file from its secrets.
// Without the file a release build is still a build, only unsigned: the
// emulator installs the debug build, and nobody is handed an unsigned
// release.
val keystoreProps = Properties().also { props ->
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { props.load(it) }
}

android {
    // The identity a phone remembers forever: applicationId cannot change
    // after the first outside install without every user uninstalling
    // (12.6, D22). io.github.deskit_app.deskit — the GitHub home, no
    // domain purchase. It replaced the owner's original package name on
    // 2026-09-19, before any copy left his hands.
    namespace = "io.github.deskit_app.deskit"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.deskit_app.deskit"
        // 26 covers every phone still receiving updates; switchToPrevious-
        // InputMethod needs 28 and is guarded at the call site.
        minSdk = 26
        // Play asks API 36 of new apps (12.6); that bump rides with the
        // AGP / SDK upgrade of the Play submission step, not before.
        targetSdk = 34
        // Three numbers, his ask (2026-09-13): bump the last for a fix,
        // the middle for something new — in the VERSION file, nowhere
        // else; versionCode follows on its own. The PC's /api/version
        // computes ime_min and ime_latest with this same line (12.9).
        versionCode = deskitNumbers[0] * 10000 + deskitNumbers[1] * 100 + deskitNumbers[2]
        versionName = deskitVersion
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            // The build that goes on GitHub Releases and later Play:
            // release-signed when keystore.properties is there, never
            // debuggable, not minified (1.2 MB; nothing to gain and a
            // stack trace to lose).
            isMinifyEnabled = false
            isDebuggable = false
            if (keystoreProps.isNotEmpty()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies { }
