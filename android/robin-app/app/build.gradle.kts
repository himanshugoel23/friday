import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

fun prop(name: String): String = providers.gradleProperty(name).get()

android {
    namespace = "app.robin.parent"
    compileSdk = 34

    defaultConfig {
        applicationId = prop("robin.applicationId")
        minSdk = 26
        targetSdk = 34
        versionCode = prop("robin.versionCode").toInt()
        versionName = prop("robin.versionName")
        // Brand and server come from build properties; nothing is hard-coded in source.
        resValue("string", "app_name", prop("robin.brandName"))
        buildConfigField("String", "BASE_URL", "\"" + prop("robin.baseUrl") + "\"")
        buildConfigField("String", "BRAND_NAME", "\"" + prop("robin.brandName") + "\"")
    }
    buildFeatures { buildConfig = true }
    // Two editions from the same code. `full` = widget + SOS + in-app voice + floating mic bubble (its permissions and
    // components come from src/full/AndroidManifest.xml). `lite` = no bubble, no overlay/foreground-service/boot/notification
    // permissions (the safe Play fallback). Logic is shared; only the manifest and BuildConfig.BUBBLE_ENABLED differ.
    flavorDimensions += "edition"
    productFlavors {
        create("full") {
            dimension = "edition"
            buildConfigField("boolean", "BUBBLE_ENABLED", "true")
        }
        create("lite") {
            dimension = "edition"
            buildConfigField("boolean", "BUBBLE_ENABLED", "false")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildTypes {
        release {
            isMinifyEnabled = false // no signing config here: Play signing is a later founder step
        }
    }
    lint { abortOnError = false }
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation(project(":core"))
    // Deliberately nothing else: no analytics, no Firebase, no ads, no networking library.
}
