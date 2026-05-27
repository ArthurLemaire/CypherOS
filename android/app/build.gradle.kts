import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing: android/keystore.properties (not in git) or the environment. Without either
// the release build is signed with the debug key, which still installs — fine for trying it,
// not for shipping, because updates from a differently signed build are refused by Android.
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
fun signing(key: String): String? = keystoreProps.getProperty(key) ?: System.getenv("OPENMUSE_" + key.uppercase())
val storeFilePath = signing("storeFile")
val hasReleaseKey = storeFilePath != null && rootProject.file(storeFilePath).exists()

android {
    namespace = "io.github.openmuseagent.openmuse"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.openmuseagent.openmuse"
        minSdk = 26
        targetSdk = 36
        versionCode = 500
        versionName = "0.5.0"
    }

    signingConfigs {
        if (hasReleaseKey) {
            create("release") {
                storeFile = rootProject.file(storeFilePath!!)
                storePassword = signing("storePassword")
                keyAlias = signing("keyAlias")
                keyPassword = signing("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = if (hasReleaseKey) signingConfigs.getByName("release") else signingConfigs.getByName("debug")
        }
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }

    // one APK for every ABI: there is no native code in the app itself
    packaging {
        resources.excludes += setOf("META-INF/*.kotlin_module", "META-INF/versions/**")
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-ktx:1.11.0")
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("com.google.android.material:material:1.13.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0") { isTransitive = false }
    implementation("com.google.zxing:core:3.5.3")
}
