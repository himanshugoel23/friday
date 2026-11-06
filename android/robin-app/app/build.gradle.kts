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
