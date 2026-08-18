pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        // [T-android-vad] RealTimeCutVADLibraryForAndroid ships via JitPack
        // only. Same author and same underlying stack (Silero + ONNX Runtime +
        // WebRTC APM) as the RealTimeCutVADLibrary SPM package iOS already
        // uses, so both platforms segment speech with the same model and the
        // same tunables.
        maven { url = uri("https://jitpack.io") }
    }
}

rootProject.name = "Minis"
include(":app")
