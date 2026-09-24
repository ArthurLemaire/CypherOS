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
fun signing(key: String): String? = keystoreProps.getProperty(key) ?: System.getenv("NANOMUSE_" + key.uppercase())
val storeFilePath = signing("storeFile")
val hasReleaseKey = storeFilePath != null && rootProject.file(storeFilePath).exists()

android {
    namespace = "io.github.nanomuse.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.nanomuse.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 100
        versionName = "0.1.0"
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

    // Two APKs from the same code (docs/local-runtime.md):
    //  - local:   nanoMuse runs on the phone itself — PRoot and the Alpine root file system
    //             (android/app/src/local/) are inside; arm64 only, as the runtime is
    //  - connect: the thin shell that connects to `nanomuse serve` on a computer; every ABI
    flavorDimensions += "mode"
    productFlavors {
        create("local") {
            dimension = "mode"
            buildConfigField("boolean", "LOCAL_RUNTIME", "true")
            ndk { abiFilters += "arm64-v8a" }
        }
        create("connect") {
            dimension = "mode"
            buildConfigField("boolean", "LOCAL_RUNTIME", "false")
            versionNameSuffix = "-connect"
        }
    }

    androidResources {
        // the root file system is xz already; the tar inside would not shrink again
        noCompress += listOf("xz", "tar")
    }

    packaging {
        resources.excludes += setOf("META-INF/*.kotlin_module", "META-INF/versions/**")
        // proot and its loader are executables kept as .so so the installer extracts them
        // to the one place under /data an app may exec from; do not compress or page-align away
        jniLibs.useLegacyPackaging = true
    }

    testOptions.unitTests.isReturnDefaultValues = true
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
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    // xz decompression for the root file system (pure Java, public domain)
    implementation("org.tukaani:xz:1.10")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
}
