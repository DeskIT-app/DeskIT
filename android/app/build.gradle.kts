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

// The release keystore (DISTRIBUTION_PLAN.md 12.7) is NOT read here, on
// purpose (2026-11-28). Gradle builds the release unsigned —
// app-release-unsigned.apk — and apksigner signs it afterwards: in CI, a job
// of its own in release.yml that holds the two secrets and runs no Gradle, no
// plugin and nothing downloaded; on the owner's PC, dev/keyboard_key.py
// --sign, which hands apksigner the passphrase in its environment. So the
// passphrase is never in a file (no keystore.properties) and the build that
// runs third-party plugins never holds the key. Both refuse an APK whose
// signer is not the certificate android/release-cert.sha256 pins. The
// keystore lives outside every checkout (dev/keyboard_key.py); the gitignore
// still lists keystore.properties and *.jks so a stray copy never lands.

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

    buildTypes {
        debug {
            // The fake account of dev/android/fake_pc.py, for the emulator:
            // `gradle assembleDebug -PdeskitAccount=http://10.0.2.2:18791`.
            // A build-time fact and never a setting, so nothing on a phone
            // can point the app at another server. Without the property the
            // app speaks to the real project (Account.kt).
            resValue("string", "account_server",
                     (project.findProperty("deskitAccount") as String?) ?: "")
            // The fake Groq and Gemini of dev/android/fake_cloud.py, the same way:
            // `-PdeskitCloud=http://10.0.2.2:18793`. Without it, the real providers.
            resValue("string", "cloud_server",
                     (project.findProperty("deskitCloud") as String?) ?: "")
        }
        release {
            resValue("string", "account_server", "")
            resValue("string", "cloud_server", "")
            // The build that goes on GitHub Releases as
            // DeskIT-keyboard-<version>.apk, and later Play: unsigned out
            // of Gradle (signed by apksigner, above), never debuggable, not
            // minified (1.2 MB; nothing to gain and a stack trace to lose).
            isMinifyEnabled = false
            isDebuggable = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies { }

// The formats against what the real vault.py wrote (src/test, a plain main):
// `gradle jvmChecks --offline`. JUnit is not in this build's offline cache and
// the app has no dependencies, so the checks do not bring one in for this.
tasks.register<JavaExec>("jvmChecks") {
    dependsOn("compileDebugUnitTestKotlin", "compileDebugKotlin")
    mainClass.set("io.github.deskit_app.deskit.CryptChecksKt")
    classpath = files(
        layout.buildDirectory.dir("tmp/kotlin-classes/debug"),
        layout.buildDirectory.dir("tmp/kotlin-classes/debugUnitTest"),
    ) + configurations.getByName("debugUnitTestRuntimeClasspath")
}
