import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("org.jetbrains.kotlin.jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    // org.json is part of the Android platform at run time, so it is compile-only here; tests use the JVM jar.
    compileOnly("org.json:json:20240303")
    testImplementation("org.json:json:20240303")
    testImplementation("junit:junit:4.13.2")
}

tasks.test {
    // The shared contract fixtures live in the Python test tree so both sides read the same files.
    val dir = rootProject.projectDir.resolve("../../tests/robindevice/contract").canonicalFile
    systemProperty("contract.dir", dir.path)
    inputs.dir(dir)
    testLogging {
        events("passed", "failed", "skipped")
        showStandardStreams = false
    }
}
